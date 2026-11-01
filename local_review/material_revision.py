"""Canonical factor-only render revisions. No Blender, shader/image processing or physics."""
import copy,hashlib,json,math,re,struct
from pathlib import Path
from substance_physics_scatter.fileio import io_path
import job_assets,pbr_contract as pbr,canonical_contract

FACTOR_KEYS={'base_color_factor','roughness_factor','metallic_factor'}
GLB_LIMIT=64*1024*1024

def digest(raw):return hashlib.sha256(raw).hexdigest()
def identity(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def factors(value):
    if type(value) is not dict or not value or set(value)-FACTOR_KEYS:raise ValueError('Factor fields: linear RGB BaseColor, Roughness, Metallic only')
    result={}
    for key,v in value.items():
        values=v if key=='base_color_factor' else [v]
        if type(values) is not list or len(values)!=(3 if key=='base_color_factor' else 1) or any(type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1 for n in values):raise ValueError('Factors require finite0..1; BaseColor is linear RGB3')
        result[key]=[float(n) for n in values] if key=='base_color_factor' else float(v)
    return result

def split_glb(raw):
    if len(raw)<20 or len(raw)>GLB_LIMIT or struct.unpack_from('<III',raw)!=(0x46546c67,2,len(raw)):raise ValueError('Canonical GLB2 header/budget')
    chunks=[];at=12
    while at<len(raw):
        if len(chunks)>=16 or at+8>len(raw):raise ValueError('GLB chunk count/header')
        length,kind=struct.unpack_from('<II',raw,at);end=at+8+length
        if length%4 or end>len(raw):raise ValueError('GLB chunk size/alignment')
        chunks.append((kind,raw[at+8:end]));at=end
    if not chunks or chunks[0][0]!=0x4e4f534a or sum(k==0x4e4f534a for k,_ in chunks)!=1:raise ValueError('GLB unique first JSON chunk')
    doc=pbr.rawjson(chunks[0][1])
    if type(doc) is not dict or doc.get('asset',{}).get('version')!='2.0':raise ValueError('GLB requires glTF2 JSON')
    if any('uri' in b for b in doc.get('buffers',[])) or any('uri' in i for i in doc.get('images',[])):raise ValueError('Factor-only revision requires embedded GLB resources')
    return doc,chunks

def edit_glb(raw,records,edits):
    if type(edits) is not dict or not 1<=len(edits)<=64:raise ValueError('Choose1..64 material slots')
    updated=copy.deepcopy(records);by={str(m['material_id']):m for m in updated}
    if len(by)!=len(updated):raise ValueError('Duplicate canonical material ID')
    parsed={}
    for key,value in edits.items():
        if type(key) is not str or not re.fullmatch('0|[1-9][0-9]?',key) or int(key)>63 or key not in by:raise ValueError('Unknown material slot')
        parsed[key]=factors(value)
    doc,chunks=split_glb(raw);before=copy.deepcopy(doc);materials=doc.get('materials')
    if type(materials) is not list or not 1<=len(materials)<=64:raise ValueError('Canonical GLB material list')
    mapped={}
    for material in materials:
        match=re.fullmatch('ReviewMat_(0|[1-9][0-9]?)',material.get('name',''))
        if match is None or match[1] not in by or match[1] in mapped:raise ValueError('GLB material slot mapping requires canonical reimport')
        mapped[match[1]]=material
    for key,value in parsed.items():
        if key not in mapped:raise ValueError('This material slot has no exported GLB material')
        material=mapped[key];mr=material.setdefault('pbrMetallicRoughness',{});row=by[key]
        old_color=mr.get('baseColorFactor',[1.,1.,1.,1.])
        if type(old_color) is not list or len(old_color)!=4 or old_color[3]!=1 or old_color[:3]!=row['base_color_factor'] or mr.get('roughnessFactor',1.)!=row['roughness_factor'] or mr.get('metallicFactor',1.)!=row['metallic_factor']:raise ValueError('GLB/native factors disagree; canonical reimport required')
        row.update(value)
        if 'base_color_factor' in value:mr['baseColorFactor']=[*value['base_color_factor'],1.]
        if 'roughness_factor' in value:mr['roughnessFactor']=value['roughness_factor']
        if 'metallic_factor' in value:mr['metallicFactor']=value['metallic_factor']
    encoded=json.dumps(doc,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8');encoded+=b' '*((-len(encoded))%4)
    parts=[struct.pack('<II',len(encoded),0x4e4f534a)+encoded]+[struct.pack('<II',len(data),kind)+data for kind,data in chunks[1:]]
    size=12+sum(map(len,parts))
    if size>GLB_LIMIT:raise ValueError('Revised GLB exceeds64MiB')
    result=struct.pack('<III',0x46546c67,2,size)+b''.join(parts)
    # The BIN/unknown chunks, texture links, UV/accessor/node data and slots are
    # copied losslessly. Factors are actual glTF multipliers after texture reads.
    checked,after_chunks=split_glb(result)
    if after_chunks[1:]!=chunks[1:]:raise ValueError('Non-JSON GLB chunks changed')
    restore=copy.deepcopy(checked)
    for i,m in enumerate(before['materials']):
        if str(m.get('name','')).removeprefix('ReviewMat_') not in parsed:continue
        prior=m.get('pbrMetallicRoughness',{});target=restore['materials'][i]['pbrMetallicRoughness']
        for native,gltf in (('base_color_factor','baseColorFactor'),('roughness_factor','roughnessFactor'),('metallic_factor','metallicFactor')):
            if native not in parsed[m['name'].removeprefix('ReviewMat_')]:continue
            if gltf in prior:target[gltf]=prior[gltf]
            else:target.pop(gltf,None)
        if 'pbrMetallicRoughness' not in m:restore['materials'][i].pop('pbrMetallicRoughness')
    if restore!=before:raise ValueError('Unexpected GLB JSON change outside factors')
    return result,updated

def build_revision(old,work,destination,edits,*,bindings=None):
    meta=old['metadata']
    if meta.get('schema_version')!=2 or meta.get('material_ready') is not True or not old.get('material_manifest'):raise ValueError('Material factors require a ready canonical asset; reimport this asset first')
    watch={}
    def load(path,expected,limit):
        path=job_assets.owned(path,work);raw=pbr.read(path,limit)
        if expected is not None and digest(raw)!=expected:raise ValueError('Material revision source SHA changed')
        watch[str(path)]=digest(raw);return raw
    folder=job_assets.owned(old['folder'],work)
    raw=load(folder/'scene.glb',meta['files']['scene.glb'],GLB_LIMIT)
    geometry=load(old['physics'],meta['files']['physics.obj'],32*1024*1024)
    corners=load(folder/'corners.json',meta['files']['corners.json'],8*1024*1024)
    manifest=pbr.rawjson(load(old['material_manifest'],None,1024*1024))
    pbr.exact(manifest,('version','profile','assets','textures'))
    if manifest['version']!=1 or manifest['profile']!='material' or len(manifest['assets'])!=1:raise ValueError('Canonical material manifest profile')
    row=manifest['assets'][0]
    if row['asset_id']!=old['asset_id'] or row['materials']!=meta['material_records'] or row['physics_obj_sha256']!=meta['files']['physics.obj'] or row['corner_data_sha256']!=meta['files']['corners.json'] or job_assets.owned(row['corner_data_path'],work)!=folder/'corners.json':raise ValueError('Material/geometry identity mismatch')
    for texture in manifest['textures']:load(texture['path'],texture['content_sha256'],8*1024*1024)
    for path,h in old.get('source_hashes',{}).items():load(path,h,32*1024*1024)
    new_raw,records=edit_glb(raw,meta['material_records'],edits) if edits else (raw,copy.deepcopy(meta['material_records']))
    available=None;source_bindings=old.get('material_source_bindings') or {str(row['material_id']):{role+'_texture':copy.deepcopy(row[role+'_texture']) for role in ('base_color','roughness','metallic','normal')} for row in meta['material_records']}
    if bindings:
        import texture_revision
        available=texture_revision.library(old,manifest)
        edit_glb(raw,meta['material_records'],{str(r['material_id']):{k:r[k] for k in FACTOR_KEYS} for r in meta['material_records'] if str(r['material_id']) in bindings})
        new_raw,records=texture_revision.edit_glb(new_raw,records,bindings,source_bindings,available,load)
    if records==meta['material_records']:return copy.deepcopy(old),False
    canonical_contract.validate(geometry,corners,records,True)
    target=job_assets.owned(destination,work)
    if io_path(target).exists():raise ValueError('New immutable material revision directory required')
    io_path(target).mkdir(parents=True,exist_ok=False)
    def save(name,data):
        with io_path(target/name).open('xb') as f:f.write(data)
    save('scene.glb',new_raw);save('physics.obj',geometry);save('corners.json',corners)
    revised=copy.deepcopy(old);revised['folder']=str(target)
    revised['metadata']['files']['scene.glb']=digest(new_raw);revised['metadata']['material_records']=records
    revised['render_revision']=digest(new_raw);revised['material_revision']=identity(records)
    revised['url']=f'/api/assets/{old["asset_id"]}/scene.glb?revision={digest(new_raw)}'
    if bindings:
        revised.setdefault('material_source_bindings',source_bindings)
        revised['material_texture_library']=list(available.values())
        used={binding['texture_id'] for row in records for role in ('base_color','roughness','metallic','normal') if (binding:=row[role+'_texture']) is not None}
        for uploaded in old.get('manual_textures',[]):
            if uploaded['texture_id'] in used:
                load(uploaded['source_path'],uploaded['source_sha256'],8*1024*1024)
                revised['source_hashes'][uploaded['source_path']]=uploaded['source_sha256']
                if uploaded.get('provenance_path'):
                    load(uploaded['provenance_path'],uploaded['provenance_sha256'],1024*1024)
                    revised['source_hashes'][uploaded['provenance_path']]=uploaded['provenance_sha256']
        for ui in revised['metadata'].get('materials',[]):
            if type(ui) is dict:
                row=next(r for r in records if r['material_id']==ui['material_id'])
                for role in ('base_color','roughness','metallic','normal'):
                    binding=row[role+'_texture'];ui['roles'][role]=dict(mode='texture' if binding else 'none',binding=copy.deepcopy(binding),status='manual' if binding else 'geometric_fallback' if role=='normal' else 'constant')
        revised['metadata']['texture_preview_profile']='local viewer: BC Linear uses declared GLB extras; data/normal roles are Non-Color; opaque UV0 four-role PBR only'

    revised.setdefault('material_source_factors',{str(m['material_id']):{k:copy.deepcopy(m[k]) for k in FACTOR_KEYS} for m in meta['material_records']})
    manifest=copy.deepcopy(manifest);manifest['assets'][0]['materials']=records;manifest['assets'][0]['corner_data_path']=str(target/'corners.json')
    if bindings:manifest['textures']=[available[tid] for tid in sorted(used)]
    save('material-manifest.json',json.dumps(manifest,indent=2,allow_nan=False).encode('utf-8'))
    revised['material_manifest']=str(target/'material-manifest.json')
    save('metadata.json',json.dumps(revised['metadata'],indent=2,allow_nan=False).encode('utf-8'))
    for path,h in watch.items():
        if digest(pbr.read(path,GLB_LIMIT))!=h:raise ValueError('Material source changed before adoption')
    if digest(pbr.read(target/'scene.glb',GLB_LIMIT))!=revised['render_revision']:raise ValueError('Revised GLB write verification failed')
    return revised,True
