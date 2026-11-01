"""N1 artifact contract / pure fixtures only. Native executions belong to coordinator."""
import copy,hashlib,json,math,os,re,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'output/evidence/local-review-native-N1/09fc40f043f540de968e6daba52196ee'
LIMIT=8*1024*1024
def digest(raw):return hashlib.sha256(raw).hexdigest()
def exact(value,fields):
    if type(value) is not dict or set(value)!=set(fields):raise ValueError('Exact field set required')
def hexsha(v):
    if type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v):raise ValueError('SHA type/value')
    return v
def number(v,lo=-math.inf,hi=math.inf):
    if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('Finite non-bool number required')
    return v
def load(raw):
    if len(raw)>LIMIT:raise ValueError('Artifact byte budget')
    def pairs(items):
        d={}
        for k,v in items:
            if k in d:raise ValueError('Duplicate JSON key')
            d[k]=v
        return d
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
def file_bytes(root,name):
    if name not in ('hulls-v1.json','review-v1.json','result.json'):raise ValueError('Fixed artifact basename required')
    p=root/name
    if p.is_symlink() or p.resolve().parent!=root.resolve() or p.stat().st_size>LIMIT:raise ValueError('Owned file budget/path')
    raw=p.read_bytes()
    if len(raw)!=p.stat().st_size:raise ValueError('Read length changed')
    return raw
def manifest(data,assets):
    exact(data,('version','profile','assets','textures'))
    if type(data['version']) is not int or data['version']!=1 or data['profile']!='geometry_only' or data['textures']!=[]:raise ValueError('N1 geometry_only schema')
    if type(data['assets']) is not list or not 1<=len(data['assets'])<=6 or len(data['assets'])!=len(assets):raise ValueError('Asset closure')
    actual={}
    for row in data['assets']:
        exact(row,('asset_id','physics_obj_sha256'));aid=row['asset_id'];h=hexsha(row['physics_obj_sha256'])
        if not isinstance(aid,str) or not re.fullmatch('[0-9a-f]{32}',aid) or aid in actual:raise ValueError('Asset ID/duplicate')
        actual[aid]=h
    if actual!={a['asset_id']:a['content_hash'] for a in assets}:raise ValueError('Asset identity binding')
def validate(root,event,request,build_hash,binary_hash):
    review=request['review_v1'];exact(review,('version','manifest_path','manifest_sha256','export_hulls','bake_pbr'))
    if type(review['version']) is not int or review['version']!=1 or review['export_hulls'] is not True or review['bake_pbr'] is not False:raise ValueError('N1 active flag set')
    mp=Path(review['manifest_path']);owner=root.parent.parent if root.parent.name=='runs' else root
    if not mp.resolve().is_relative_to(owner.resolve()) or mp.is_symlink() or mp.stat().st_size>1024*1024:raise ValueError('Owned manifest path/budget')
    manifest_raw=mp.read_bytes()
    if digest(manifest_raw)!=review['manifest_sha256']:raise ValueError('Input manifest bytes changed')
    manifest(load(manifest_raw),request['assets'])
    exact(event,('event','schema_version','job_id','result_path','review'))
    if event['event']!='completed' or type(event['schema_version']) is not int or event['schema_version']!=2 or event['job_id']!=request['job_id'] or Path(event['result_path']).resolve()!=root.resolve()/'result.json':raise ValueError('Event job/result identity')
    ref=event['review'];exact(ref,('version','path','sha256','bytes'))
    raw=file_bytes(root,ref['path'])
    if type(ref['version']) is not int or ref['version']!=1 or type(ref['bytes']) is not int or len(raw)!=ref['bytes'] or digest(raw)!=hexsha(ref['sha256']):raise ValueError('Sidecar SHA/length')
    doc=load(raw);exact(doc,('version','job_id','result_sha256','manifest_sha256','producer','artifacts'))
    if type(doc['version']) is not int or doc['version']!=1 or doc['job_id']!=request['job_id'] or doc['manifest_sha256']!=request['review_v1']['manifest_sha256'] or doc['result_sha256']!=digest(file_bytes(root,'result.json')):raise ValueError('Sidecar source/result binding')
    exact(doc['producer'],('implementation_version','build_fingerprint','binary_sha256'))
    if doc['producer']!=dict(implementation_version='0.4.0-review.1',build_fingerprint=hexsha(build_hash),binary_sha256=hexsha(binary_hash)):raise ValueError('Review producer identity')
    artifacts=doc['artifacts'];exact(artifacts,('hulls',));row=artifacts['hulls']
    exact(row,('path','byte_sha256','byte_count','format','schema_version','hull_count','aggregate_vertex_count','aggregate_face_count','hulls'))
    for key in ('byte_count','schema_version','hull_count','aggregate_vertex_count','aggregate_face_count'):
        if type(row[key]) is not int or row[key]<0:raise ValueError('Exact integer descriptor required')
    raw=file_bytes(root,row['path'])
    if row['path']!='hulls-v1.json' or row['byte_count']!=len(raw) or row['byte_sha256']!=digest(raw) or row['format']!='JSON' or row['schema_version']!=1:raise ValueError('Hull artifact bytes/format')
    hull=load(raw);exact(hull,('schema_version','coordinate_system','units','hulls'))
    if type(hull['schema_version']) is not int or hull['schema_version']!=1 or hull['coordinate_system']!='RH_Z_UP' or hull['units']!='meters' or type(hull['hulls']) is not list:raise ValueError('Hull envelope')
    result=load(file_bytes(root,'result.json'));expected={p['asset_id']:p['scale'] for p in result['poses']};present={};vertices=faces=0;counts=[]
    for h in hull['hulls']:
        exact(h,('asset_id','physics_obj_sha256','built_scale','coordinate_space','center_of_mass_scaled','convex_radius','vertices','faces','Jolt_version','shape_type','max_hull_points','construction_tolerance'))
        aid=h['asset_id']
        if aid not in expected or aid in present or h['built_scale']!=expected[aid] or h['coordinate_space']!='scaled_asset_origin_local' or h['Jolt_version']!='5.2.0' or h['shape_type']!='ConvexHull' or h['max_hull_points']!=256:raise ValueError('Hull identity/scale')
        if h['physics_obj_sha256']!={a['asset_id']:a['content_hash'] for a in request['assets']}[aid]:raise ValueError('Hull OBJ SHA')
        number(h['built_scale'],0,100);number(h['convex_radius'],0);number(h['construction_tolerance'],0)
        if len(h['center_of_mass_scaled'])!=3:raise ValueError('COM dimensions')
        for v in h['center_of_mass_scaled']:number(v)
        v=h['vertices'];f=h['faces']
        if not 3<=len(v)<=256 or not 2<=len(f)<=512:raise ValueError('Hull counts')
        for point in v:
            if len(point)!=3:raise ValueError('Point dimensions')
            for component in point:number(component)
        for face in f:
            if not 3<=len(face)<=256 or len(set(face))!=len(face) or any(type(i) is not int or not 0<=i<len(v) for i in face):raise ValueError('Face index/count')
        present[aid]=True;vertices+=len(v);faces+=len(f);counts.append(dict(asset_id=aid,vertex_count=len(v),face_count=len(f)))
    if set(present)!=set(expected) or len(present)!=row['hull_count'] or vertices!=row['aggregate_vertex_count'] or faces!=row['aggregate_face_count'] or counts!=row['hulls']:raise ValueError('Hull descriptors/pose closure')
    return doc,hull

class ReviewN1(unittest.TestCase):
    def setUp(self):
        self.root=EVIDENCE/'pure'/uuid.uuid4().hex;self.root.mkdir(parents=True);self.aid='a'*32;self.job='b'*32;self.build='c'*64;self.binary='d'*64
        mp=self.root/'geometry-manifest.json';mp.write_text(json.dumps(dict(version=1,profile='geometry_only',assets=[dict(asset_id=self.aid,physics_obj_sha256='e'*64)],textures=[])),encoding='utf8')
        self.request=dict(job_id=self.job,assets=[dict(asset_id=self.aid,content_hash='e'*64)],review_v1=dict(version=1,manifest_path=str(mp),manifest_sha256=digest(mp.read_bytes()),export_hulls=True,bake_pbr=False))
        self.hull=dict(schema_version=1,coordinate_system='RH_Z_UP',units='meters',hulls=[dict(asset_id=self.aid,physics_obj_sha256='e'*64,built_scale=.25,coordinate_space='scaled_asset_origin_local',center_of_mass_scaled=[.25]*3,convex_radius=0.,vertices=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],faces=[[0,2,1],[0,1,3],[0,3,2],[1,2,3]],Jolt_version='5.2.0',shape_type='ConvexHull',max_hull_points=256,construction_tolerance=.001)])
        (self.root/'result.json').write_text(json.dumps(dict(poses=[dict(asset_id=self.aid,scale=.25)])),encoding='utf8');self.seal()
    def seal(self):
        raw=json.dumps(self.hull).encode();(self.root/'hulls-v1.json').write_bytes(raw)
        self.doc=dict(version=1,job_id=self.job,result_sha256=digest(file_bytes(self.root,'result.json')),manifest_sha256=self.request['review_v1']['manifest_sha256'],producer=dict(implementation_version='0.4.0-review.1',build_fingerprint=self.build,binary_sha256=self.binary),artifacts=dict(hulls=dict(path='hulls-v1.json',byte_sha256=digest(raw),byte_count=len(raw),format='JSON',schema_version=1,hull_count=len(self.hull['hulls']),aggregate_vertex_count=sum(len(h['vertices']) for h in self.hull['hulls']),aggregate_face_count=sum(len(h['faces']) for h in self.hull['hulls']),hulls=[dict(asset_id=h['asset_id'],vertex_count=len(h['vertices']),face_count=len(h['faces'])) for h in self.hull['hulls']])))
        self.reseal()
    def reseal(self):
        raw=json.dumps(self.doc).encode();(self.root/'review-v1.json').write_bytes(raw);self.event=dict(event='completed',schema_version=2,job_id=self.job,result_path=str(self.root/'result.json'),review=dict(version=1,path='review-v1.json',sha256=digest(raw),bytes=len(raw)))
    def check(self):return validate(self.root,self.event,self.request,self.build,self.binary)
    def test_positive_and_no_scale_second_application(self):
        _,h=self.check();point=h['hulls'][0]['vertices'][1];self.assertEqual([2-point[1],3+point[0],4+point[2]],[2,4,4]);self.assertNotEqual([2,3+.25,4],[2,4,4])
    def test_empty_actual_shapes_are_not_synthesized(self):
        self.hull['hulls']=[];(self.root/'result.json').write_text('{"poses":[]}',encoding='utf8');self.seal();self.assertEqual(self.check()[1]['hulls'],[])
    def test_artifact_and_sidecar_raw_tamper(self):
        for name in ('hulls-v1.json','review-v1.json'):
            p=self.root/name;raw=p.read_bytes();p.write_bytes(raw+b' ')
            with self.subTest(name=name),self.assertRaises(ValueError):self.check()
            p.write_bytes(raw)
    def test_exact_role_path_count_and_producer_negatives(self):
        original=copy.deepcopy(self.doc)
        for mutation in (lambda d:d['artifacts'].update(extra={}),lambda d:d['artifacts']['hulls'].update(path='../hulls-v1.json'),lambda d:d['artifacts']['hulls'].update(hull_count=2),lambda d:d['artifacts']['hulls'].update(hull_count=True),lambda d:d.update(job_id='0'*32),lambda d:d['producer'].update(binary_sha256='0'*64)):
            self.doc=copy.deepcopy(original);mutation(self.doc);self.reseal()
            with self.assertRaises(ValueError):self.check()
        self.doc=original;self.reseal();self.request['review_v1']['export_hulls']=False
        with self.assertRaises(ValueError):self.check()
    def test_invalid_face_and_pose_scale_reject_after_reseal(self):
        self.hull['hulls'][0]['faces'][0][0]=999;self.seal()
        with self.assertRaises(ValueError):self.check()
        self.hull['hulls'][0]['faces'][0][0]=0;self.hull['hulls'][0]['built_scale']=.5;self.seal()
        with self.assertRaises(ValueError):self.check()
    def test_geometry_manifest_closure_types_and_duplicates(self):
        assets=[dict(asset_id=self.aid,content_hash='e'*64)];data=dict(version=1,profile='geometry_only',assets=[dict(asset_id=self.aid,physics_obj_sha256='e'*64)],textures=[]);manifest(data,assets)
        for mutation in (lambda d:d.update(version=True),lambda d:d.update(profile='material'),lambda d:d['assets'].append(d['assets'][0]),lambda d:d['assets'][0].update(extra=1),lambda d:d['assets'][0].update(physics_obj_sha256='0'*64)):
            bad=copy.deepcopy(data);mutation(bad)
            with self.assertRaises(ValueError):manifest(bad,assets)
        with self.assertRaises(ValueError):load(b'{"version":1,"version":2}')
    def test_artifact_budget_and_numeric_bool(self):
        with self.assertRaises(ValueError):load(b' '*(LIMIT+1))
        with self.assertRaises(ValueError):number(True)
        with self.assertRaises(ValueError):number(float('nan'))
    def test_legacy_constants_and_optout_source_boundary(self):
        source=(ROOT/'worker/main.cpp').read_text(encoding='utf8');self.assertIn('constexpr const char* VERSION = "0.3.0"',source);self.assertIn('review.enabled?&review:nullptr',source)
        old=(EVIDENCE/'before/main.cpp').read_text(encoding='utf8');start='static json bake(';stop='\n#ifdef _WIN32';self.assertEqual(old[old.index(start):old.index(stop)],source[source.index(start):source.index(stop)])
        self.assertIn('if(!request.contains("review_v1"))return context',(ROOT/'worker/review_hulls.h').read_text())

if __name__=='__main__':unittest.main()
