"""N2 pure preparation/oracles. --prepare NEW_DIRECTORY never runs a native worker.

Analytic fixtures are TEST_ONLY, not Jolt observations. The coordinator owns actual
simulate/bake requests and valid pose-source provenance; this helper never edits it.
"""
from pathlib import Path
import copy,hashlib,io,json,math,struct,sys,tempfile,unittest,zlib
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'output/evidence/local-review-native-N2/91b257fe3d6647bab69c9971ef203791'
PIXELS=ROOT/'output/evidence/N2-pixel-fixtures/2e0eb425dce145fbb640e2241a914ef5'
AXIS=ROOT/'output/evidence/N2-uv-axis-fixture/a52c0a1ce5bb48b182a8b850f379da6b'
LIMIT=8*1024*1024
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
    p=Path(path);r=Path(root).resolve()
    if p.is_symlink() or not p.resolve().is_relative_to(r) or p.resolve()==r:raise ValueError('Owned path')
    return p.resolve()
def read(path,limit=LIMIT):
    path=Path(path);size=path.stat().st_size
    if size>limit:raise ValueError('File budget')
    raw=path.read_bytes()
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
def linear(v):return v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4
def srgb(v):return 12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055
def q(v):return math.floor(max(0,min(1,v))*255+.5)
def sample_rgba(pixels,u,v,repeat=True,color_space='linear'):
    u=u%1 if repeat else max(0,min(1,u));v=v%1 if repeat else max(0,min(1,v));x=u*512-.5;y=(1-v)*512-.5;ix=math.floor(x);iy=math.floor(y);fx=x-ix;fy=y-iy
    def tap(x,y):
        x=x%512 if repeat else max(0,min(511,x));y=y%512 if repeat else max(0,min(511,y));rgb=pixels[(y*512+x)*4:(y*512+x)*4+3];return [linear(a/255) if color_space=='sRGB' else a/255 for a in rgb]
    taps=[tap(ix,iy),tap(ix+1,iy),tap(ix,iy+1),tap(ix+1,iy+1)];weights=[(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy];return [sum(t[k]*w for t,w in zip(taps,weights)) for k in range(3)]
def unit(v):
    length=math.sqrt(sum(x*x for x in v))
    if not length:raise ValueError('Zero vector')
    return [x/length for x in v]
def tangent_normal(rgb,hand=1,dx=False):
    n=unit([rgb[0]*2-1,(rgb[1]*2-1)*(-1 if dx else 1),rgb[2]*2-1]);return [n[0],n[1]*hand,n[2]]
def prepare(out):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False);textures=[];byname={};inputs={}
    for source in [PIXELS/n for n in ('basecolor.png','packed.png','normal_gl.png','uvchecker.png')]+[AXIS/'uv_axis_rgb.png']:
        raw=read(source);inputs[str(source)]=sha(raw)
        with Image.open(io.BytesIO(raw)) as image:
            rgb=image.convert('RGB').tobytes();rgba=image.convert('RGBA');data=io.BytesIO();rgba.save(data,format='PNG');encoded=data.getvalue()
            if rgba.tobytes()[0::4]!=rgb[0::3] or rgba.tobytes()[1::4]!=rgb[1::3] or rgba.tobytes()[2::4]!=rgb[2::3]:raise ValueError('RGBA derivative altered RGB')
        path=out/source.name;path.write_bytes(encoded);tid=sha(encoded);row=dict(texture_id=tid,path=str(path),content_sha256=tid,width=512,height=512,channels=4,bit_depth=8);textures.append(row);byname[source.name]=row
    # Preserve original triangle order, normals and UV; derive an explicit per-triangle tangent.
    vertices=[];uvs=[];normals=[];triangles=[]
    for line in (PIXELS/'fixture.obj').read_text(encoding='utf8').splitlines():
        words=line.split()
        if not words:continue
        if words[0]=='v':vertices.append([f32(float(v)) for v in words[1:]])
        if words[0]=='vt':uvs.append([float(v) for v in words[1:]])
        if words[0]=='vn':normals.append([float(v) for v in words[1:]])
        if words[0]=='f':
            refs=[[int(v)-1 for v in word.split('/')] for word in words[1:]];p=[vertices[r[0]] for r in refs];uv=[uvs[r[1]] for r in refs];n=[normals[r[2]] for r in refs];du1=uv[1][0]-uv[0][0];dv1=uv[1][1]-uv[0][1];du2=uv[2][0]-uv[0][0];dv2=uv[2][1]-uv[0][1];det=du1*dv2-du2*dv1;e1=[p[1][k]-p[0][k] for k in range(3)];e2=[p[2][k]-p[0][k] for k in range(3)];t=unit([(e1[k]*dv2-e2[k]*dv1)/det for k in range(3)]);bit=[(e2[k]*du1-e1[k]*du2)/det for k in range(3)];cross=[n[0][1]*t[2]-n[0][2]*t[1],n[0][2]*t[0]-n[0][0]*t[2],n[0][0]*t[1]-n[0][1]*t[0]];w=1 if sum(a*b for a,b in zip(cross,bit))>0 else -1
            triangles.append(dict(tri_id=len(triangles),shape_id='test_box',material_id=0,positions=p,uv0=uv,normals=n,tangents=[t+[w] for _ in range(3)]))
    obj=out/'physics.obj';obj.write_text(''.join('v '+' '.join(format(x,'.9g') for x in p)+'\n' for t in triangles for p in t['positions'])+''.join(f'f {3*i+1} {3*i+2} {3*i+3}\n' for i in range(len(triangles))),encoding='utf8');corner=out/'corners.json';corner.write_text(json.dumps(dict(version=1,triangle_count=len(triangles),triangles=triangles),allow_nan=False),encoding='utf8')
    def b(name,channel='rgb',space='linear',normal=False):
        row=dict(texture_id=byname[name]['texture_id'],channel=channel,uv_set=0,wrap_u='clamp',wrap_v='clamp',filter='bilinear',color_space=space)
        if normal:row['normal_convention']='OpenGL'
        return row
    mat=dict(material_id=0,base_color_factor=[1,1,1],roughness_factor=1,metallic_factor=1,base_color_texture=b('basecolor.png',space='sRGB'),roughness_texture=b('packed.png','g'),metallic_texture=b('packed.png','b'),normal_texture=None)
    aid='f'*32;asset=dict(asset_id=aid,physics_obj_sha256=sha(obj.read_bytes()),corner_data_path=str(corner),corner_data_sha256=sha(corner.read_bytes()),materials=[mat]);manifest=dict(version=1,profile='material',assets=[asset],textures=[byname[n] for n in ('basecolor.png','packed.png')]);(out/'material-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    variants={};factor=copy.deepcopy(mat);factor.update(base_color_factor=[.25,.5,.75],roughness_factor=.5,metallic_factor=0,base_color_texture=None,roughness_texture=None,metallic_texture=None);variants['factor_only']=factor
    for name in ('uvchecker.png','uv_axis_rgb.png','normal_gl.png'):
        m=copy.deepcopy(mat);m['base_color_texture']=b(name,space='sRGB') if name!='normal_gl.png' else mat['base_color_texture'];m['normal_texture']=b(name,normal=True) if name=='normal_gl.png' else None;variants[name]=m
    (out/'variants.json').write_text(json.dumps(variants,indent=2),encoding='utf8');report=dict(TEST_ONLY=True,worker_executions=0,analytic_pose_not_Jolt_observation=True,asset_id=aid,inputs=inputs,derived_files={str(p):sha(p.read_bytes()) for p in out.iterdir() if p.is_file()},texture_rows=textures,expected=dict(constant_BC=[128,64,192],roughness=64,metallic=192,linear_factor_BC=[137,188,225],empty_BC=[0,0,0],empty_R=255,empty_M=0));(out/'preparation.json').write_text(json.dumps(report,indent=2),encoding='utf8');return manifest,{aid:obj},report
def seal_request(request_path,manifest_source,export_hulls=False):
    """Copy only material inputs into an existing owned job; add review_v1 only.
    Caller must use Jobs.prepare and retain its valid origin/pose protocol unchanged.
    """
    request_path=Path(request_path).resolve();request=rawjson(read(request_path));out=Path(request['output_directory']).resolve();root=out.parent.parent
    if out!=request_path.parent or out.parent.name!='runs' or out.name!=request['job_id']:raise ValueError('Owned job/request')
    source=rawjson(read(manifest_source));doc=copy.deepcopy(source);folder=root/'inputs'/('review-pbr-'+request['job_id']);folder.mkdir(parents=True,exist_ok=False)
    for a in doc['assets']:
        data=read(a['corner_data_path']);target=folder/(sha(data)+'-corners.json');target.write_bytes(data);a['corner_data_path']=str(target)
    for t in doc['textures']:
        data=read(t['path']);target=folder/(sha(data)+'.png')
        if not target.exists():target.write_bytes(data)
        t['path']=str(target)
    physics={a['asset_id']:Path(a['path']) for a in request['assets']};validate_manifest(doc,physics,root);path=folder/'manifest.json';path.write_text(json.dumps(doc,indent=2,allow_nan=False),encoding='utf8');request['review_v1']=dict(version=1,manifest_path=str(path),manifest_sha256=sha(read(path)),export_hulls=export_hulls,bake_pbr=True);request_path.write_text(json.dumps(request,indent=2,allow_nan=False),encoding='utf8');return request

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
    if side['producer']!=dict(implementation_version='0.4.0-review.2',build_fingerprint=build_hash,binary_sha256=binary_hash):raise ValueError('Producer identity')
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

class PurePBR(unittest.TestCase):
    def setUp(self):self.folder=EVIDENCE/'pure'/next(tempfile._get_candidate_names());self.doc,self.physics,self.report=prepare(self.folder)
    def test_rgba_derivatives_and_manifest_match_original_positions(self):
        self.assertEqual(validate_manifest(self.doc,self.physics,self.folder)['textures'],2)
        for name,h in self.report['inputs'].items():self.assertEqual(sha(Path(name).read_bytes()),h)
    def test_closed_manifest_and_corner_negatives(self):
        for mutate in (lambda d:d.update(version=True),lambda d:d.update(extra=1),lambda d:d['assets'][0].update(physics_obj_sha256='0'*64),lambda d:d['textures'][0].update(channels=3),lambda d:d['assets'][0]['materials'][0]['roughness_texture'].update(channel='rgb'),lambda d:d['assets'][0]['materials'][0]['base_color_texture'].update(uv_set=True)):
            bad=copy.deepcopy(self.doc);mutate(bad)
            with self.assertRaises(ValueError):validate_manifest(bad,self.physics,self.folder)
        a=self.doc['assets'][0];path=Path(a['corner_data_path']);raw=read(path);doc=rawjson(raw);doc['triangles'][0]['positions'][0][0]+=.001;changed=json.dumps(doc).encode();path.write_bytes(changed);a['corner_data_sha256']=sha(changed)
        with self.assertRaisesRegex(ValueError,'Position exact'):validate_manifest(self.doc,self.physics,self.folder)
    def test_color_space_packed_and_factor_oracles(self):
        self.assertEqual([q(srgb(v)) for v in (.25,.5,.75)],[137,188,225]);pixels=png(read(self.folder/'basecolor.png'),True)['pixels'];self.assertEqual([q(srgb(v)) for v in sample_rgba(pixels,.25,.25,color_space='sRGB')],[128,64,192]);packed=png(read(self.folder/'packed.png'),True)['pixels'];self.assertEqual([q(v) for v in sample_rgba(packed,.25,.25)],[17,64,192])
    def test_asymmetric_uv_v_flip_repeat_clamp(self):
        pixels=png(read(self.folder/'uv_axis_rgb.png'),True)['pixels']
        for x,y in ((17,31),(400,7),(9,450)):
            expected=list(pixels[(y*512+x)*4:(y*512+x)*4+3]);u=(x+.5)/512;v=1-(y+.5)/512;self.assertEqual([q(a) for a in sample_rgba(pixels,u,v)],expected);self.assertEqual([q(a) for a in sample_rgba(pixels,u+2,v-3)],expected)
        self.assertEqual([q(a) for a in sample_rgba(pixels,-1,2,False)],list(pixels[:3]))
    def test_dx_gl_and_handedness_explicit(self):
        gl=[128/255,192/255,239/255];dx=[gl[0],1-gl[1],gl[2]]
        for hand in (-1,1):self.assertEqual([q(v*.5+.5) for v in tangent_normal(gl,hand)],[q(v*.5+.5) for v in tangent_normal(dx,hand,True)])
        self.assertNotEqual(tangent_normal(gl,-1),tangent_normal(gl,1))
    def test_source_boundaries_and_bake_only(self):
        source=(ROOT/'worker/main.cpp').read_text(encoding='utf8');before=(EVIDENCE/'before/worker/main.cpp').read_text(encoding='utf8');start='static json bake(';end='\n#ifdef _WIN32';self.assertEqual(source[source.index(start):source.index(end)],before[before.index(start):before.index(end)]);self.assertIn('struct Tri {V a,b,c,n;};',source)
        p=(ROOT/'worker/review_pbr_input.h').read_text(encoding='utf8');self.assertIn('!c.hull_export||op=="simulate_bake"',p);self.assertIn('c.pbr=true',p);self.assertIn('mask_inflate',p)
    def test_actual_early_guard_predicates_and_main_callsite(self):
        import ast,re
        source=(ROOT/'worker/main.cpp').read_text(encoding='utf8')
        class J:
            def __init__(self,value):self.value=value
            def is_object(self):return type(self.value) is dict
            def contains(self,key):return key in self.value
            def at(self,key):return J(self.value[key])
            def is_boolean(self):return type(self.value) is bool
            def get_bool(self):
                if not self.is_boolean():raise ValueError('Non-bool')
                return self.value
        def predicate(name,**values):
            # Execute the production return expression; only C++ boolean spelling is adapted.
            expression=re.search(r'static bool '+name+r'\([^\n]*\)\{\s*return ([^;]+);\s*\}',source).group(1)
            expression=expression.replace('.get<bool>()','.get_bool()').replace('&&',' and ').replace('||',' or ').replace('!',' not ')
            return eval(compile(ast.parse(expression.strip(),mode='eval'),name,'eval'),{'__builtins__':{}},values)
        def allowed(op,r):return predicate('review_operation_allowed',op=op,material_bake_only=predicate('review_bake_flags',r=J(r)))
        material={'bake_pbr':True,'export_hulls':False};self.assertTrue(allowed('bake',material))
        for r in ({'bake_pbr':False,'export_hulls':True},{'bake_pbr':True,'export_hulls':True},{'bake_pbr':1,'export_hulls':False},{'bake_pbr':True,'export_hulls':0},{},None):self.assertFalse(allowed('bake',r))
        for op in ('simulate','simulate_bake'):self.assertTrue(allowed(op,{'bake_pbr':False,'export_hulls':True}))
        for op in ('hash_probe','mask_probe','selection_probe','placement_probe','unknown'):self.assertFalse(allowed(op,material))
        self.assertIn('require(review_operation_allowed(op,review_bake_flags(request.at("review_v1")))',source)
        self.assertLess(source.index('require(review_operation_allowed('),source.index('if(op=="hash_probe")'))
    def test_seal_request_and_artifact_tamper_failure(self):
        aid=self.report['asset_id'];job='a'*32;root=self.folder/'jobroot';run=root/'runs'/job;run.mkdir(parents=True);asset=root/'physics.obj';asset.write_bytes(read(self.physics[aid]));request=dict(job_id=job,operation='bake',output_directory=str(run),assets=[dict(asset_id=aid,path=str(asset),content_hash=sha(read(asset)))],bake=dict(resolution=16,normal='OpenGL'));path=run/'request.json';path.write_text(json.dumps(request),encoding='utf8');request=seal_request(path,self.folder/'material-manifest.json');self.assertFalse(request['review_v1']['export_hulls']);result=dict(poses=[],maps={'resolution':16,'normal_convention':'OpenGL'});(run/'result.json').write_text(json.dumps(result),encoding='utf8');artifacts={}
        for role,mode,value in (('basecolor','RGB',(128,64,192)),('roughness','L',64),('metallic','L',192),('normal_material','RGB',(128,128,255))):
            p=run/(role+'.png');Image.new(mode,(16,16),value).save(p);data=read(p);row=dict(path=p.name,byte_sha256=sha(data),byte_count=len(data),format='PNG',width=16,height=16,bit_depth=8,color_type='RGB' if mode=='RGB' else 'GREY',color_space='sRGB' if role=='basecolor' else 'linear')
            if role=='normal_material':row['normal_convention']='OpenGL'
            artifacts[role]=row
        side=dict(version=1,job_id=job,result_sha256=sha(read(run/'result.json')),manifest_sha256=request['review_v1']['manifest_sha256'],producer=dict(implementation_version='0.4.0-review.2',build_fingerprint='b'*64,binary_sha256='c'*64),artifacts=artifacts)
        def seal():
            raw=json.dumps(side).encode();(run/'review-v1.json').write_bytes(raw);return dict(event='completed',schema_version=2,job_id=job,result_path=str(run/'result.json'),review=dict(version=1,path='review-v1.json',sha256=sha(raw),bytes=len(raw)))
        event=seal();validate_artifacts(run,event,request,'b'*64,'c'*64)
        for mutate in (lambda d:d['artifacts']['roughness'].update(path='../roughness.png'),lambda d:d['artifacts']['basecolor'].update(width=32),lambda d:d.update(job_id='d'*32),lambda d:d['artifacts'].update(unknown={}),lambda d:d['producer'].update(implementation_version='0.4.0-review.1')):
            saved=copy.deepcopy(side);mutate(side)
            with self.assertRaises(ValueError):validate_artifacts(run,seal(),request,'b'*64,'c'*64)
            side=saved
        event=seal();p=run/'metallic.png';raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        with self.assertRaises(ValueError):validate_artifacts(run,event,request,'b'*64,'c'*64)
        geometry=root/'geometry.json';geometry.write_text(json.dumps(dict(version=1,profile='geometry_only',assets=[dict(asset_id=aid,physics_obj_sha256=request['assets'][0]['content_hash'])],textures=[])),encoding='utf8');request=copy.deepcopy(request);request['operation']='simulate_bake';request['review_v1'].update(bake_pbr=False,export_hulls=True,manifest_path=str(geometry),manifest_sha256=sha(read(geometry)));hull=run/'hulls-v1.json';hull.write_text(json.dumps(dict(schema_version=1,coordinate_system='RH_Z_UP',units='meters',hulls=[])),encoding='utf8');data=read(hull);side['manifest_sha256']=request['review_v1']['manifest_sha256'];side['artifacts']=dict(hulls=dict(path=hull.name,byte_sha256=sha(data),byte_count=len(data),format='JSON',schema_version=1,hull_count=0,aggregate_vertex_count=0,aggregate_face_count=0,hulls=[]));validate_artifacts(run,seal(),request,'b'*64,'c'*64)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--prepare':
        _,_,report=prepare(sys.argv[2]);print(json.dumps(report,indent=2))
    else:unittest.main()
