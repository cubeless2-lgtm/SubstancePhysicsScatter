"""Closed N2 host contract derived from accepted native actual validator.
No worker or SDK execution. N1 remains in review_contract.py.
"""
from pathlib import Path
import hashlib,io,json,math,struct,zlib,os,re
from PIL import Image
from substance_physics_scatter.fileio import io_path,logical_path
from substance_physics_scatter import compat
LIMIT=8*1024*1024

def implementation_for_request(request):
    if request.get('physics_input_format_version')!=3:return '0.4.0-review.2'
    compat.formats(request)
    compat.periodic_identity(request.get('periodic'))
    compat.simulation(request['simulation'],version=3)
    return '0.4.0-review.3'
def hexsha(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('SHA type/value')
    return value
def sha(raw):return hashlib.sha256(raw).hexdigest()

def rawjson(raw):
    if len(raw)>LIMIT:raise ValueError('JSON byte budget')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('Duplicate field')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def exact(doc,keys):
    if type(doc) is not dict or set(doc)!=set(keys):raise ValueError('Exact fields')

def num(v,lo=-math.inf,hi=math.inf):
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Finite non-bool number')
    return v

def whole(v,lo,hi):
    if type(v) is not int or not lo<=v<=hi:raise ValueError('Integer bound')
    return v

def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]

def vector(v,n):
    if type(v) is not list or len(v)!=n:raise ValueError('Vector shape')
    return [num(x) for x in v]

def owned(path,root):
    original=Path(os.path.abspath(path));base=Path(os.path.abspath(root));p=logical_path(path);r=logical_path(root)
    if original==base or not original.is_relative_to(base) or p==r or not p.is_relative_to(r):raise ValueError('Owned path')
    cursor=base
    for part in original.relative_to(base).parts:
        cursor/=part
        if io_path(cursor).exists() and getattr(io_path(cursor).lstat(),'st_file_attributes',0)&0x400:raise ValueError('Owned reparse path')
    return p

def read(path,limit=LIMIT):
    path=Path(path);size=io_path(path).stat().st_size
    if size>limit:raise ValueError('File budget')
    raw=io_path(path).read_bytes()
    if len(raw)!=size:raise ValueError('Changed read')
    return raw

def png(raw,rgba=False):
    if len(raw)>LIMIT or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('PNG signature/budget')
    at=8;ihdr=None;end=False
    while at<len(raw):
        if len(raw)-at<12:raise ValueError('PNG truncated')
        n=int.from_bytes(raw[at:at+4],'big');typ=raw[at+4:at+8];stop=at+n+12
        if stop>len(raw) or zlib.crc32(raw[at+4:at+8+n])!=int.from_bytes(raw[at+8+n:stop],'big'):raise ValueError('PNG length/CRC')
        if typ==b'IHDR':
            if ihdr is not None or at!=8 or n!=13:raise ValueError('PNG IHDR')
            ihdr=struct.unpack('>IIBBBBB',raw[at+8:at+21])
        if typ==b'IEND':
            if n or stop!=len(raw):raise ValueError('PNG end/trailing')
            end=True
        at=stop
    if not end or ihdr is None or ihdr[2]!=8 or ihdr[4:]!=(0,0,0) or not 1<=ihdr[0]<=8192 or not 1<=ihdr[1]<=8192 or ihdr[0]*ihdr[1]>16777216:raise ValueError('PNG format/bounds')
    if rgba and ihdr[:4]!=(512,512,8,6):raise ValueError('RGBA512 descriptor')
    with Image.open(io.BytesIO(raw)) as im:im.load();size=im.size;mode=im.mode;pixels=im.tobytes()
    if rgba and (mode!='RGBA' or pixels[3::4]!=b'\xff'*(512*512)):raise ValueError('Opaque RGBA')
    return dict(width=size[0],height=size[1],mode=mode,pixels=pixels,header=ihdr)

def validate_manifest(doc,physics,root):
    exact(doc,('version','profile','assets','textures'));whole(doc['version'],1,1)
    if doc['profile']!='material' or type(doc['assets']) is not list or not 1<=len(doc['assets'])<=6 or type(doc['textures']) is not list or len(doc['textures'])>64:raise ValueError('Profile/count')
    textures={};used=set();total=0
    for t in doc['textures']:
        exact(t,('texture_id','path','content_sha256','width','height','channels','bit_depth'));tid=t['texture_id']
        if type(tid) is not str or len(tid)!=64 or tid in textures:raise ValueError('Texture identity')
        for key,value in (('width',512),('height',512),('channels',4),('bit_depth',8)):whole(t[key],value,value)
        raw=read(owned(t['path'],root));total+=len(raw)
        if total>64*1024*1024 or sha(raw)!=t['content_sha256']:raise ValueError('Texture SHA/budget')
        png(raw,True);textures[tid]=t
    def binding(b,role):
        if b is None:return
        exact(b,('texture_id','channel','uv_set','wrap_u','wrap_v','filter','color_space')+(('normal_convention',) if role=='normal' else ()))
        if b['texture_id'] not in textures:raise ValueError('Unknown texture')
        used.add(b['texture_id']);whole(b['uv_set'],0,0)
        if b['channel'] not in (('rgb',) if role in ('base_color','normal') else ('r','g','b')) or b['filter']!='bilinear' or b['wrap_u'] not in ('repeat','clamp') or b['wrap_v'] not in ('repeat','clamp'):raise ValueError('Binding')
        if b['color_space'] not in (('sRGB','linear') if role=='base_color' else ('linear',)):raise ValueError('Color space')
        if role=='normal' and b['normal_convention'] not in ('OpenGL','DirectX'):raise ValueError('Normal convention')
    ids=set();corner_total=0
    for a in doc['assets']:
        exact(a,('asset_id','physics_obj_sha256','corner_data_path','corner_data_sha256','materials'));aid=a['asset_id']
        if aid in ids or aid not in physics:raise ValueError('Asset identity')
        ids.add(aid);obj=read(owned(physics[aid],root),256*1024*1024)
        if sha(obj)!=a['physics_obj_sha256']:raise ValueError('Physics SHA')
        positions=[];faces=[]
        for line in obj.decode('utf8').splitlines():
            words=line.split()
            if words and words[0]=='v':positions.append([f32(float(v)) for v in words[1:4]])
            if words and words[0]=='f':
                if len(words)!=4:raise ValueError('Canonical triangles only')
                faces.append([int(x.split('/')[0])-1 for x in words[1:]])
        if len(positions)<4 or not 1<=len(faces)<5000:raise ValueError('Physics geometry bounds')
        if type(a['materials']) is not list or not 1<=len(a['materials'])<=64:raise ValueError('Material count')
        mats={}
        for m in a['materials']:
            exact(m,('material_id','base_color_factor','roughness_factor','metallic_factor','base_color_texture','roughness_texture','metallic_texture','normal_texture'));mid=whole(m['material_id'],0,63)
            if mid in mats:raise ValueError('Duplicate material')
            mats[mid]=m
            for v in vector(m['base_color_factor'],3):num(v,0,1)
            for k in ('roughness_factor','metallic_factor'):num(m[k],0,1)
            for role in ('base_color','roughness','metallic','normal'):binding(m[role+'_texture'],role)
        raw=read(owned(a['corner_data_path'],root));corner_total+=len(raw)
        if corner_total>48*1024*1024 or sha(raw)!=a['corner_data_sha256']:raise ValueError('Corner SHA/budget')
        c=rawjson(raw);exact(c,('version','triangle_count','triangles'));whole(c['version'],1,1);whole(c['triangle_count'],len(faces),len(faces))
        if len(c['triangles'])!=len(faces):raise ValueError('Triangle closure')
        for i,t in enumerate(c['triangles']):
            exact(t,('tri_id','shape_id','material_id','positions','uv0','normals','tangents'));whole(t['tri_id'],i,i)
            if type(t['shape_id']) is not str or not t['shape_id'] or whole(t['material_id'],0,63) not in mats:raise ValueError('Shape/material')
            for field in ('positions','uv0','normals','tangents'):
                if type(t[field]) is not list or len(t[field])!=3:raise ValueError('Corners shape')
            signs=[]
            for k in range(3):
                if vector(t['positions'][k],3)!=positions[faces[i][k]]:raise ValueError('Position exact')
                vector(t['uv0'][k],2);n=vector(t['normals'][k],3);tan=vector(t['tangents'][k],4)
                if sum(v*v for v in n)==0 or sum(v*v for v in tan[:3])==0 or tan[3] not in (-1,1):raise ValueError('Normal/tangent')
                signs.append(tan[3])
            if len(set(signs))!=1:raise ValueError('Handedness')
    if ids!=set(physics) or used!=set(textures):raise ValueError('Full asset/texture closure')
    return dict(assets=len(ids),textures=len(textures),corner_bytes=corner_total)

def validate_artifacts(root,event,request,build_hash,binary_hash):
    """Independent raw/PNG/producer validator; caller also runs unchanged Jobs.validate."""
    root=Path(root).resolve();owner=root.parent.parent;flags=request['review_v1'];exact(flags,('version','manifest_path','manifest_sha256','export_hulls','bake_pbr'));whole(flags['version'],1,1)
    if type(flags['bake_pbr']) is not bool or type(flags['export_hulls']) is not bool or not (flags['bake_pbr'] or flags['export_hulls']) or root!=Path(request['output_directory']).resolve() or root.name!=request['job_id'] or root.parent.name!='runs':raise ValueError('Review job/flags')
    material_raw=read(owned(flags['manifest_path'],owner),1024*1024)
    if sha(material_raw)!=flags['manifest_sha256']:raise ValueError('Manifest raw SHA')
    material=rawjson(material_raw)
    if flags['bake_pbr']:validate_manifest(material,{a['asset_id']:a['path'] for a in request['assets']},owner)
    else:
        exact(material,('version','profile','assets','textures'));whole(material['version'],1,1)
        if material['profile']!='geometry_only' or material['textures']!=[] or not 1<=len(material['assets'])<=6:raise ValueError('Geometry-only profile')
        supplied={}
        for a in material['assets']:
            exact(a,('asset_id','physics_obj_sha256'))
            if a['asset_id'] in supplied:raise ValueError('Geometry asset duplicate')
            supplied[a['asset_id']]=a['physics_obj_sha256']
        if supplied!={a['asset_id']:a['content_hash'] for a in request['assets']}:raise ValueError('Geometry asset closure')
    exact(event,('event','schema_version','job_id','result_path','review'));whole(event['schema_version'],2,2)
    if event['event']!='completed' or event['job_id']!=request['job_id'] or Path(event['result_path']).resolve()!=root/'result.json':raise ValueError('Event identity')
    ref=event['review'];exact(ref,('version','path','sha256','bytes'));whole(ref['version'],1,1)
    if ref['path']!='review-v1.json':raise ValueError('Fixed sidecar path')
    raw=read(owned(root/ref['path'],root));whole(ref['bytes'],len(raw),len(raw))
    if sha(raw)!=ref['sha256']:raise ValueError('Sidecar raw SHA')
    side=rawjson(raw);exact(side,('version','job_id','result_sha256','manifest_sha256','producer','artifacts'));whole(side['version'],1,1);result_raw=read(root/'result.json',16*1024*1024);result=rawjson(result_raw)
    if side['job_id']!=request['job_id'] or side['result_sha256']!=sha(result_raw) or side['manifest_sha256']!=flags['manifest_sha256']:raise ValueError('Sidecar source identity')
    implementation=implementation_for_request(request)
    if implementation=='0.4.0-review.3':
        compat.formats(result)
        if any(result.get(k)!=request[k] for k in compat.PERIODIC_VERSIONS):raise ValueError('Periodic result contract pair')
    if side['producer']!=dict(implementation_version=implementation,build_fingerprint=build_hash,binary_sha256=binary_hash):raise ValueError('Producer identity')
    expected=({'basecolor','roughness','metallic','normal_material'} if flags['bake_pbr'] else set())|({'hulls'} if flags['export_hulls'] else set());exact(side['artifacts'],expected);decoded={};resolution=request['bake']['resolution']
    for role,row in side['artifacts'].items():
        if role=='hulls':
            exact(row,('path','byte_sha256','byte_count','format','schema_version','hull_count','aggregate_vertex_count','aggregate_face_count','hulls'))
            if row['path']!='hulls-v1.json' or row['format']!='JSON':raise ValueError('Fixed hull path/format')
        else:
            exact(row,('path','byte_sha256','byte_count','format','width','height','bit_depth','color_type','color_space')+(('normal_convention',) if role=='normal_material' else ()))
            if row['path']!=role+'.png' or row['format']!='PNG':raise ValueError('Fixed PNG path/format')
        data=read(owned(root/row['path'],root));whole(row['byte_count'],len(data),len(data))
        if row['byte_sha256']!=sha(data):raise ValueError('Artifact raw SHA')
        if role=='hulls':
            hull=rawjson(data);exact(hull,('schema_version','coordinate_system','units','hulls'));whole(hull['schema_version'],1,1);whole(row['schema_version'],1,1)
            if hull['coordinate_system']!='RH_Z_UP' or hull['units']!='meters':raise ValueError('Hull coordinates')
            expected_assets={p['asset_id']:p['scale'] for p in result['poses']};counts=[];seen=set();vertices=faces=0
            for h in hull['hulls']:
                exact(h,('asset_id','physics_obj_sha256','built_scale','coordinate_space','center_of_mass_scaled','convex_radius','vertices','faces','Jolt_version','shape_type','max_hull_points','construction_tolerance'));aid=h['asset_id']
                if aid in seen or aid not in expected_assets or h['built_scale']!=expected_assets[aid] or h['physics_obj_sha256']!=next(a['content_hash'] for a in request['assets'] if a['asset_id']==aid) or h['coordinate_space']!='scaled_asset_origin_local':raise ValueError('Hull asset binding')
                if h['Jolt_version']!='5.2.0' or h['shape_type']!='ConvexHull':raise ValueError('Hull shape')
                whole(h['max_hull_points'],256,256);vector(h['center_of_mass_scaled'],3);num(h['convex_radius'],0);num(h['construction_tolerance'],0);whole(len(h['vertices']),3,256);whole(len(h['faces']),2,512)
                for v in h['vertices']:vector(v,3)
                for f in h['faces']:
                    whole(len(f),3,256)
                    if len(set(f))!=len(f):raise ValueError('Hull duplicate face index')
                    for index in f:whole(index,0,len(h['vertices'])-1)
                seen.add(aid);vertices+=len(h['vertices']);faces+=len(h['faces']);counts.append(dict(asset_id=aid,vertex_count=len(h['vertices']),face_count=len(h['faces'])))
            if seen!=set(expected_assets) or row['hulls']!=counts:raise ValueError('Hull pose/count closure')
            for field,value in (('hull_count',len(seen)),('aggregate_vertex_count',vertices),('aggregate_face_count',faces)):whole(row[field],value,value)
        else:
            parsed=png(data);rgb=role in ('basecolor','normal_material');mode='RGB' if rgb else 'L'
            for field,value in (('width',resolution),('height',resolution),('bit_depth',8)):whole(row[field],value,value)
            if parsed['width']!=resolution or parsed['height']!=resolution or parsed['mode']!=mode or parsed['header'][3]!=(2 if rgb else 0) or row['color_type']!=('RGB' if rgb else 'GREY') or row['color_space']!=('sRGB' if role=='basecolor' else 'linear'):raise ValueError('PNG descriptor')
            if role=='normal_material' and row['normal_convention']!=request['bake']['normal']:raise ValueError('Output normal convention')
            decoded[role]=parsed
    return side,decoded
