"""New-run immutable closure. Imported files/catalog and previous jobs are read-only."""
import copy,hashlib,json,os
from pathlib import Path
from substance_physics_scatter.fileio import io_path,logical_path
import pbr_contract as pbr

CAP=512*1024*1024
def digest(raw):return hashlib.sha256(raw).hexdigest()
def owned(path,root):
    original=Path(os.path.abspath(path));base=Path(os.path.abspath(root));p=logical_path(path);r=logical_path(root)
    if original==base or not original.is_relative_to(base) or p==r or not p.is_relative_to(r):raise ValueError('Job closure path boundary')
    current=base
    for part in original.relative_to(base).parts:
        current/=part
        if io_path(current).exists() and getattr(io_path(current).lstat(),'st_file_attributes',0)&0x400:raise ValueError('Job closure reparse path')
    return p
def data(path,root,limit):
    path=owned(path,root);size=io_path(path).stat().st_size
    if size>limit:raise ValueError('Closure file budget')
    raw=io_path(path).read_bytes()
    if len(raw)!=size:raise ValueError('Closure input changed length')
    return raw
def verify(index,work,originals=False):
    for item in index['files']:
        raw=data(item['path'],work,item['bytes'])
        if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:raise ValueError('Sealed job closure changed')
        if originals:
            raw=data(item['source_path'],work,item['bytes'])
            if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:raise ValueError('Source changed during execution')

def seal(records,request,work,check_space,protocol_files=()):
    request=copy.deepcopy(request);run=owned(request['output_directory'],work);folder=run/'inputs/review-assets'
    if io_path(folder).exists():raise ValueError('New closure directory required')
    records={a['asset_id']:a for a in records};pbr_enabled=all(a['metadata'].get('material_ready') is True for a in records.values());plans=[];textures={};rows=[];renders={};total=0;reasons=[]
    def plan(role,aid,source,target,hash_value,limit):
        nonlocal total
        source=owned(source,work);target=owned(target,run);size=io_path(source).stat().st_size
        if size>limit or total+size>CAP:raise ValueError('Job closure file/aggregate budget')
        total+=size;plans.append(dict(role=role,asset_id=aid,source_path=str(source),path=str(target),sha256=pbr.hexsha(hash_value),bytes=size));return str(target)
    for active in request['assets']:
        aid=active['asset_id'];a=records[aid];meta=a['metadata'];target=folder/aid;files=meta['files'];original_physics=active['path'];active['path']=plan('physics',aid,original_physics,target/'physics.obj',active['content_hash'],32*1024*1024)
        if files.get('physics.obj') is not None and files['physics.obj']!=active['content_hash']:raise ValueError('Catalog physics identity differs')
        glb=plan('render',aid,Path(a['folder'])/'scene.glb',target/'scene.glb',files['scene.glb'],64*1024*1024)
        renders[aid]=dict(glb_path=glb,glb_sha256=files['scene.glb'],render_revision=a.get('render_revision',files['scene.glb']),material_revision=a.get('material_revision'),url=f'/api/render/{request["job_id"]}/{aid}')
        names=set()
        if pbr_enabled and not a.get('source_hashes'):raise ValueError('Ready asset is missing source-original hashes')
        for original,hash_value in a.get('source_hashes',{}).items():
            name=Path(original).name
            if name.casefold() in names:raise ValueError('Duplicate original basename')
            names.add(name.casefold());plan('original',aid,original,target/'originals'/name,hash_value,32*1024*1024)
        if 'corners.json' in files:corner_path=plan('corners',aid,Path(a['folder'])/'corners.json',target/'corners.json',files['corners.json'],8*1024*1024)
        if not meta.get('material_ready'):reasons.append(a.get('name',aid)+': material/UV/TBN 입력 미완료')
        if not pbr_enabled:continue
        if not a.get('material_manifest') or 'corners.json' not in files:raise ValueError('Ready asset is missing material inputs')
        raw=data(a['material_manifest'],work,1024*1024);source=pbr.rawjson(raw);pbr.exact(source,('version','profile','assets','textures'))
        pbr.whole(source['version'],1,1)
        if source['profile']!='material' or type(source['assets']) is not list or len(source['assets'])!=1 or type(source['textures']) is not list or len(source['textures'])>64:raise ValueError('Source material profile')
        row=copy.deepcopy(source['assets'][0]);pbr.exact(row,('asset_id','physics_obj_sha256','corner_data_path','corner_data_sha256','materials'))
        if row['asset_id']!=aid or row['physics_obj_sha256']!=active['content_hash'] or row['corner_data_sha256']!=files['corners.json'] or row['materials']!=meta['material_records']:raise ValueError('Source material/geometry revision differs')
        if logical_path(row['corner_data_path'])!=logical_path(Path(a['folder'])/'corners.json'):raise ValueError('Corner locator differs')
        row['corner_data_path']=corner_path;rows.append(row);plan('source_material_manifest',aid,a['material_manifest'],target/'source-material-manifest.json',digest(raw),1024*1024)
        used={binding['texture_id'] for m in row['materials'] for role in ('base_color','roughness','metallic','normal') if (binding:=m[role+'_texture']) is not None};seen=set()
        for t in source['textures']:
            pbr.exact(t,('texture_id','path','content_sha256','width','height','channels','bit_depth'));tid=t['texture_id']
            pbr.hexsha(tid);pbr.hexsha(t['content_sha256'])
            for key,value in (('width',512),('height',512),('channels',4),('bit_depth',8)):pbr.whole(t[key],value,value)
            if tid in seen:raise ValueError('Duplicate source texture ID')
            seen.add(tid)
            if tid not in used:continue  # Explicit used-binding projection, not an unknown-field sanitizer.
            if tid in textures:
                if {k:v for k,v in textures[tid].items() if k!='path'}!={k:v for k,v in t.items() if k!='path'}:raise ValueError('Texture ID collision')
                if digest(data(t['path'],work,8*1024*1024))!=t['content_sha256']:raise ValueError('Source texture cache alias SHA differs')
                continue
            t=copy.deepcopy(t);t['path']=plan('texture',aid,t['path'],folder/'textures'/(tid+'.png'),t['content_sha256'],8*1024*1024);textures[tid]=t
        if not used<=seen:raise ValueError('Material texture binding missing')
    mask=request.get('scatter_mask')
    if mask is not None:mask['path']=plan('mask','',mask['path'],folder/'mask.png',mask['content_hash'],32*1024*1024)
    protocol=[];seen_paths={item['path'] for item in plans}
    if type(protocol_files) not in (list,tuple) or len(protocol_files)>128:raise ValueError('Protocol closure count budget')
    for item in protocol_files:
        pbr.exact(item,('role','asset_id','source_path','path','sha256','bytes'))
        if item['role']!='protocol_provenance' or item['asset_id']!='':raise ValueError('Protocol closure role')
        target=owned(item['path'],run);source=owned(item['source_path'],work);pbr.hexsha(item['sha256']);pbr.whole(item['bytes'],1,16*1024*1024)
        if str(target) in seen_paths or total+item['bytes']>CAP:raise ValueError('Protocol closure duplicate/byte budget')
        raw=data(target,work,item['bytes'])
        if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:raise ValueError('Protocol closure sealed SHA')
        raw=data(source,work,item['bytes'])
        if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:raise ValueError('Protocol closure original SHA')
        seen_paths.add(str(target));total+=item['bytes'];protocol.append(copy.deepcopy(item))
    if len(plans)+len(protocol)>256:raise ValueError('Job closure count budget')
    check_space(total+128*1024*1024)
    io_path(folder).mkdir(parents=True,exist_ok=False)
    for item in plans:
        raw=data(item['source_path'],work,item['bytes'])
        if len(raw)!=item['bytes'] or digest(raw)!=item['sha256']:raise ValueError('Closure source SHA changed')
        path=Path(item['path']);io_path(path.parent).mkdir(parents=True,exist_ok=True)
        with io_path(path).open('xb') as stream:stream.write(raw)
        if digest(data(path,work,item['bytes']))!=item['sha256']:raise ValueError('Closure copied SHA differs')
    manifest=dict(version=1,profile='material' if pbr_enabled else 'geometry_only',assets=rows if pbr_enabled else [dict(asset_id=a['asset_id'],physics_obj_sha256=a['content_hash']) for a in request['assets']],textures=list(textures.values()) if pbr_enabled else [])
    encoded=json.dumps(manifest,indent=2,allow_nan=False).encode('utf8')
    if len(encoded)>1024*1024:raise ValueError('Job material manifest budget')
    if pbr_enabled:pbr.validate_manifest(manifest,{a['asset_id']:a['path'] for a in request['assets']},run.parent.parent)
    path=folder/'manifest.json'
    with io_path(path).open('xb') as stream:stream.write(encoded)
    request['review_v1']=dict(version=1,manifest_path=str(path),manifest_sha256=digest(encoded),export_hulls=request.get('operation')!='bake',bake_pbr=pbr_enabled)
    aliases=[];alias_keys=set()
    for aid,record in records.items():
        for alias in record.get('stored_source_aliases',[]):
            pbr.exact(alias,('source_path','current_path','sha256'));source=str(owned(alias['source_path'],work));h=pbr.hexsha(alias['sha256'])
            if source!=alias['source_path'] or record['source_hashes'].get(alias['current_path'])!=h:raise ValueError('Historical source alias identity')
            matches=[p for p in plans if p['role']=='original' and p['asset_id']==aid and p['source_path']==alias['current_path'] and p['sha256']==h]
            if len(matches)!=1 or (aid,source) in alias_keys or len(aliases)>=256:raise ValueError('Historical source alias duplicate/budget')
            alias_keys.add((aid,source));item=matches[0];aliases.append(dict(asset_id=aid,source_path=source,path=item['path'],sha256=h,bytes=item['bytes']))
    index=dict(version=1,files=plans+protocol,source_aliases=aliases,pbr=pbr_enabled,pbr_unavailable=reasons,renders=renders,total_bytes=total)
    raw=json.dumps(index,indent=2,allow_nan=False).encode('utf8')
    if len(raw)>1024*1024:raise ValueError('Job closure index byte budget')
    with io_path(folder/'closure.json').open('xb') as stream:stream.write(raw)
    return request,dict(path=str(folder/'closure.json'),sha256=digest(raw)),index
