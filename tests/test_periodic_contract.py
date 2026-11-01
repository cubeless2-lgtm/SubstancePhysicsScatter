"""P2a pure contracts only. Synthetic JSON is not Jolt/native output evidence."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import compat,maskio
from substance_physics_scatter.core import Jobs

GOLDEN=ROOT/'tests/fixtures/periodic_contract'
G=json.loads((GOLDEN/'legacy-golden.json').read_bytes())
MESH=ROOT/'tests/fixtures/cube.obj'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(json.dumps(value,ensure_ascii=False,indent=1,allow_nan=False).encode('utf-8'))

def black_png():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,16,0,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\0'*4+b'\0'+b'\0'*4))+chunk(b'IEND',b'')

def synthetic_current(root,*,version=3,empty=False,negative_zero=False):
    """Well-formed protocol records, not a physical simulation claim."""
    mesh_hash=hashlib.sha256(MESH.read_bytes()).hexdigest();cache=compat.cache_path(root,mesh_hash)
    cache.parent.mkdir(parents=True);shutil.copyfile(MESH,cache)
    rows=[dict(asset_id='a'*32,content_hash=mesh_hash,format='obj',weight=1.,scale=.25,path=str(cache))]
    sim=dict(count=1,width=2.,depth=2.,seconds=2.,seed=123456789,edges='periodic' if version==3 else 'walls',friction=0.,restitution=.05)
    mask=None
    if empty:
        image=root/'black.png';image.write_bytes(black_png());mask=maskio.snapshot(root,image)
    physical=compat.inputs(rows,sim,mask,version)
    if negative_zero:physical['simulation']['friction']=-0.
    # Non-default whitespace and original numeric tokens are deliberate provenance.
    physical_raw=json.dumps(physical,separators=(',',':'),sort_keys=False).encode('utf-8')+b'\n'
    digest=compat.sha(physical_raw);key=compat.simulation_key(digest,version)
    identity='1'*32;run=compat.safe_result(root,identity).parent;run.mkdir(parents=True)
    (run/'physics_inputs.json').write_bytes(physical_raw)
    versions=compat.versions_for_input(version)
    if version==1:versions.update(physics_contract_version=1,bake_contract_version=1)
    request=dict(schema_version=2,job_id=identity,operation='simulate_bake',worker_version='TEST_ONLY-protocol-fixture',**versions,**compat.SEMANTICS,assets=rows,simulation=sim,scatter_mask=mask,physics_input_hash=digest,physics_inputs_path=str(run/'physics_inputs.json'),simulation_key=key,key_scheme='physics_input_v1',output_directory=str(run))
    if version==3:request['periodic']=dict(compat.PERIODIC)
    poses=[] if empty else [dict(id=0,asset_id='a'*32,position=[0.,0.,.5],rotation=[0.,0.,0.,1.],scale=.25)]
    steps=0 if empty else 120;settling='not_run' if empty else 'TEST_ONLY_protocol_fixture'
    spawn=dict(requested_count=1,spawned_count=len(poses),attempt_count=0 if empty else 1,max_attempts=10,spawn_status='empty' if empty else 'complete',spawn_stop_reason='all_black' if empty else 'requested_count_reached',initial_positions=[] if empty else [[0.,0.,1.]])
    record=dict(job_id=identity,worker_version=request['worker_version'],pose_format_version=1,physics_contract_version=version,physics_input_format_version=version,key_scheme='physics_input_v1',simulation_key=key,physics_input_hash=digest,**compat.SEMANTICS,poses=copy.deepcopy(poses),steps=steps,settling_status=settling)
    if version in (2,3):record.update(copy.deepcopy(spawn),execution=dict(physics_executed=bool(poses),body_count=len(poses),steps=steps))
    if version==3:record['periodic']=dict(compat.PERIODIC)
    write(run/'origin_result.json',record);record_sha=compat.sha((run/'origin_result.json').read_bytes())
    origin=dict(job_id=identity,worker_version=request['worker_version'],physics_contract_version=version,record_sha256=record_sha)
    result=dict(request,status='completed',poses=copy.deepcopy(poses),steps=steps,source_steps=steps,settling_status=settling,execution=dict(physics_executed=bool(poses) if version in (2,3) else True,body_count=len(poses),steps=steps),pose_origin=origin,origin=dict(kind='origin_result',record_path='origin_result.json',record_sha256=record_sha))
    if version in (2,3):result.update(copy.deepcopy(spawn))
    result['pose_envelope']=dict(pose_format_version=1,**compat.SEMANTICS,poses=copy.deepcopy(poses),origin=copy.deepcopy(origin),simulation_key=key,physics_input_hash=digest,key_scheme='physics_input_v1')
    write(run/'request.json',request);write(run/'result.json',result)
    return dict(root=root,current=dict(job_id=identity),wanted=physical,request=request,result=result,run=run,physical_raw=physical_raw,record=record)

def saved(fixture,identity):
    root=fixture['root'];bundle,blobs=compat.source(root,fixture['current'],fixture['wanted'])
    run=compat.safe_result(root,identity).parent;run.mkdir(parents=True)
    raw=blobs.data[bundle['source_input_sha256']];(run/'physics_inputs.json').write_bytes(raw)
    blobs.save(run,already_present=(bundle['source_input_sha256'],))
    write(run/'pose_source.json',bundle)
    request=copy.deepcopy(fixture['request']);request.update(job_id=identity,operation='bake',worker_version='TEST_ONLY-rebake-producer',output_directory=str(run),physics_inputs_path=str(run/'physics_inputs.json'),pose_source_path=str(run/'pose_source.json'),pose_source_hash=compat.sha((run/'pose_source.json').read_bytes()))
    result=copy.deepcopy(fixture['result']);result.update(request);result.update(execution=dict(physics_executed=False,body_count=0,steps=0),rebake_source=bundle['source'])
    result['origin']=dict(kind='origin_result',record_sha256=bundle['origin']['record_sha256'],record_path='provenance/'+bundle['origin']['record_sha256']+'.json')
    write(run/'request.json',request);write(run/'result.json',result)
    return dict(fixture,current=dict(job_id=identity),request=request,result=result,run=run,physical_raw=raw)

class PeriodicContract(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='P2a_pure_한글 ');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_legacy_golden_bytes_keys_and_public_defaults_exact(self):
        self.assertEqual(compat.VERSIONS,G['default_versions'])
        for name in ('inputs','validate_raw_poses'):
            self.assertEqual(inspect.signature(getattr(compat,name)).parameters['version'].default,1)
        self.assertEqual(inspect.signature(compat.simulation_key).parameters['contract'].default,1)
        for c in G['inputs']:
            with self.subTest(case=c['name']):
                value=compat.inputs(G['rows'],c['simulation'],c['mask'],c['version']);raw=compat.encoded(value)
                self.assertEqual(raw,(GOLDEN/c['file']).read_bytes());self.assertEqual(compat.sha(raw),c['sha256'])
                self.assertEqual(compat.simulation_key(c['sha256']),c['key1']);self.assertEqual(compat.simulation_key(c['sha256'],2),c['key2'])
        self.assertEqual(compat.inputs(G['rows'],{})['physics_input_format_version'],1)
        compat.formats(dict(pose_format_version=1,physics_input_format_version=1,physics_contract_version=7,bake_contract_version=1,worker_version='TEST_ONLY_historical_positive_contract'))
    def test_ten_actual_archived_sources_bundles_blobs_unchanged(self):
        self.assertEqual(len(G['consumers']),10)
        for index,c in enumerate(G['consumers']):
            with self.subTest(cache=c['cache']):
                root=self.root/str(index);shutil.copytree(ROOT/c['cache'],root)
                bundle,blobs=compat.source(root,Jobs(root).current,c['wanted'])
                self.assertEqual(bundle,c['bundle']);self.assertEqual(sorted(blobs.data),c['blobs'])
    def test_explicit_input3_identity_and_key_separate_from_legacy(self):
        p=compat.inputs(G['rows'],dict(edges='periodic'),version=3)
        self.assertEqual(set(p),{'physics_input_format_version','assets','simulation','scatter_mask','periodic'})
        self.assertEqual(p['periodic'],dict(domain_axes='XY',representative='com_half_open',render_pose='asset_origin_same_lattice_shift',solver_contract='jolt5_2_periodic_coupled_v1',mask_sampling='initial_center_input2'))
        self.assertEqual(compat.versions_for_input(3),dict(pose_format_version=1,physics_contract_version=3,bake_contract_version=3,physics_input_format_version=3))
        self.assertEqual(compat.stored_inputs(p,3),p)
        raw=compat.encoded(p);key=compat.simulation_key(compat.sha(raw),3)
        self.assertEqual(key,hashlib.sha256(('physics_input_v1\n'+hashlib.sha256(raw).hexdigest()+'\n3\n').encode()).hexdigest())
        self.assertNotEqual(key,compat.simulation_key(compat.sha(raw),2))
        moved=copy.deepcopy(G['rows']);moved[0]['path']='elsewhere.obj';moved[1]['source_name']='display'
        self.assertEqual(compat.encoded(compat.inputs(moved,dict(edges='periodic'),version=3)),raw)
        p['periodic']['solver_contract']='modified';self.assertEqual(compat.PERIODIC['solver_contract'],'jolt5_2_periodic_coupled_v1')
    def test_default_and_wrong_version_edge_combinations_fail_closed(self):
        for version in (None,True,False,0,4,3.,'3'):
            with self.subTest(version=version),self.assertRaises(ValueError):compat.inputs(G['rows'],dict(edges='periodic'),version=version)
        for version in (1,2):
            with self.subTest(version=version),self.assertRaises(ValueError):compat.inputs(G['rows'],dict(edges='periodic'),version=version)
            physical=compat.inputs(G['rows'],{},version=version);physical['periodic']=dict(compat.PERIODIC)
            with self.assertRaises(ValueError):compat.stored_inputs(physical,version)
        for edges in ('open','walls',None,True,3):
            with self.subTest(edges=edges),self.assertRaises(ValueError):compat.inputs(G['rows'],dict(edges=edges),version=3)
        with self.assertRaises(ValueError):compat.simulation(dict(edges='periodic'))
    def test_input3_physical_policy_keys_types_and_domain_are_closed(self):
        good=compat.inputs(G['rows'],dict(edges='periodic'),version=3)
        cases=[]
        for field in good:
            c=copy.deepcopy(good);del c[field];cases.append(c)
        for field in compat.PERIODIC:
            for value in (None,True,1,'wrong'):
                c=copy.deepcopy(good);c['periodic'][field]=value;cases.append(c)
            c=copy.deepcopy(good);del c['periodic'][field];cases.append(c)
        for field in ('width','depth','count','seed','friction','restitution','seconds'):
            c=copy.deepcopy(good);c['simulation'][field]=True;cases.append(c)
        for field,value in (('width',0),('depth',float('inf')),('seed',1.5),('count',None)):
            c=copy.deepcopy(good);c['simulation'][field]=value;cases.append(c)
        for at,key in (((), 'unknown'),(('periodic',),'width'),(('simulation',),'unknown')):
            c=copy.deepcopy(good);target=c
            for component in at:target=target[component]
            target[key]=1;cases.append(c)
        c=copy.deepcopy(good);c['assets'].reverse();cases.append(c)
        c=copy.deepcopy(good);c['assets'][0]['path']='must not be in identity';cases.append(c)
        c=copy.deepcopy(good);c['scatter_mask']=dict(content_hash='c'*64,**maskio.POLICY,path='not identity');cases.append(c)
        for index,c in enumerate(cases):
            with self.subTest(index=index),self.assertRaises((ValueError,TypeError)):compat.stored_inputs(c,3)
    def test_input3_contract_pair_and_legacy_periodic_fields_rejected(self):
        record=dict(compat.PERIODIC_VERSIONS,worker_version='TEST_ONLY')
        compat.formats(record)
        for field in compat.PERIODIC_VERSIONS:
            for value in (True,None,1 if field!='pose_format_version' else 3,2 if field!='pose_format_version' else 0):
                bad=dict(record);bad[field]=value
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):compat.formats(bad)
        for v in (1,2):
            bad=dict(compat.VERSIONS,physics_input_format_version=v,worker_version='TEST_ONLY',periodic=dict(compat.PERIODIC))
            with self.assertRaises(ValueError):compat.formats(bad)
    def test_input3_source_two_saved_raw_key_origin_and_poses_unchanged(self):
        first=synthetic_current(self.root/'sim',negative_zero=True)
        root=first['root'];before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        one=saved(first,'2'*32);two=saved(one,'3'*32)
        for fixture in (first,one,two):
            bundle,blobs=compat.source(root,fixture['current'],fixture['wanted'])
            self.assertEqual(blobs.data[bundle['source_input_sha256']],first['physical_raw'])
            self.assertEqual(bundle['origin'],first['result']['pose_origin']);self.assertEqual(bundle['poses'],first['result']['poses'])
            self.assertEqual(bundle['simulation_key'],first['request']['simulation_key']);self.assertEqual(bundle['source_steps'],120)
        self.assertEqual(two['result']['execution'],dict(physics_executed=False,body_count=0,steps=0))
        self.assertEqual(two['result']['rebake_source']['job_id'],'2'*32)
        self.assertTrue(all(Path(p).read_bytes()==b for p,b in before.items()))
        self.assertIn(b'-0.0',first['physical_raw'])
    def test_input3_saved_physics_geometry_mask_solver_changes_require_resim(self):
        f=synthetic_current(self.root/'sim')
        changes=[lambda p:p['assets'][0].update(content_hash='0'*64),lambda p:p['assets'][0].update(scale=.5),lambda p:p['assets'][0].update(weight=2.),lambda p:p['simulation'].update(width=3.),lambda p:p['simulation'].update(depth=3.),lambda p:p['simulation'].update(seed=2),lambda p:p['periodic'].update(solver_contract='different'),lambda p:p.update(scatter_mask=dict(content_hash='c'*64,**maskio.POLICY))]
        for change in changes:
            wanted=copy.deepcopy(f['wanted']);change(wanted)
            with self.subTest(change=change),self.assertRaises(ValueError):compat.source(f['root'],f['current'],wanted)
    def test_input3_zero_origin_execution_and_mask_metadata_are_preserved(self):
        first=synthetic_current(self.root/'empty',empty=True)
        bundle,_=compat.source(first['root'],first['current'],first['wanted'])
        self.assertEqual(bundle['poses'],[]);self.assertEqual(bundle['source_steps'],0);self.assertEqual(bundle['spawn']['initial_positions'],[])
        self.assertEqual(bundle['spawn']['spawn_stop_reason'],'all_black')
        second=saved(first,'2'*32);bundle,_=compat.source(first['root'],second['current'],second['wanted'])
        self.assertEqual(bundle['spawn'],{k:first['record'][k] for k in compat.SPAWN_FIELDS})
        self.assertEqual(second['result']['execution'],dict(physics_executed=False,body_count=0,steps=0))
        with self.assertRaises(ValueError):compat.validate_raw_poses([],first['request']['assets'])
    def test_input3_execution_and_origin_tampering_fail(self):
        for index,(field,value) in enumerate((('steps',True),('source_steps',-1),('execution.steps',.5),('execution.body_count',True),('execution.physics_executed',False),('spawned_count',0),('initial_positions',[]),('pose_origin.physics_contract_version',2))):
            f=synthetic_current(self.root/str(index));result=f['result'];at=result;parts=field.split('.')
            for part in parts[:-1]:at=at[part]
            at[parts[-1]]=value;write(f['run']/'result.json',result)
            with self.subTest(field=field),self.assertRaises(ValueError):compat.source(f['root'],f['current'],f['wanted'])
        f=synthetic_current(self.root/'wrong_origin');record=f['record'];record['physics_input_format_version']=2;record.pop('periodic');write(f['run']/'origin_result.json',record);h=compat.sha((f['run']/'origin_result.json').read_bytes())
        for target in (f['result']['pose_origin'],f['result']['origin'],f['result']['pose_envelope']['origin']):target['record_sha256']=h
        write(f['run']/'result.json',f['result'])
        with self.assertRaisesRegex(ValueError,'origin physics/input'):compat.source(f['root'],f['current'],f['wanted'])
    def test_input3_raw_physical_unknown_policy_or_bool_rejected_without_rewrite(self):
        for index,change in enumerate((lambda p:p.update(extra=1),lambda p:p['simulation'].update(friction=True),lambda p:p['periodic'].update(domain_axes='XZ'))):
            f=synthetic_current(self.root/str(index));physical=copy.deepcopy(f['wanted']);change(physical)
            data=json.dumps(physical).encode();(f['run']/'physics_inputs.json').write_bytes(data)
            # Correct the two current descriptors so validation reaches the raw payload gate.
            h=compat.sha(data);f['request']['physics_input_hash']=h;f['result']['physics_input_hash']=h
            write(f['run']/'request.json',f['request']);write(f['run']/'result.json',f['result'])
            with self.subTest(index=index),self.assertRaises(ValueError):compat.source(f['root'],f['current'],f['wanted'])
            self.assertEqual((f['run']/'physics_inputs.json').read_bytes(),data)
    def _request_binding_counterexamples(self,field,bad):
        f=synthetic_current(self.root/'request_binding');compat.source(f['root'],f['current'],f['wanted'])
        original=copy.deepcopy(f['request']);unchanged={str(p):p.read_bytes() for p in f['run'].iterdir() if p.name!='request.json'}
        absent=object()
        for value in (bad,None,True,3,[],{},absent):
            request=copy.deepcopy(original)
            if value is absent:request.pop(field)
            else:request[field]=value
            write(f['run']/'request.json',request);raw=(f['run']/'request.json').read_bytes()
            with self.subTest(field=field,value=repr(value)),self.assertRaisesRegex(ValueError,'Input3 request/result raw key mismatch'):compat.source(f['root'],f['current'],f['wanted'])
            self.assertEqual((f['run']/'request.json').read_bytes(),raw)
            self.assertTrue(all(Path(p).read_bytes()==data for p,data in unchanged.items()))
    def _saved_binding_counterexamples(self,field,bad):
        first=synthetic_current(self.root/'saved_binding');f=saved(first,'2'*32)
        compat.source(f['root'],f['current'],f['wanted'])
        original=json.loads((f['run']/'pose_source.json').read_bytes());request=copy.deepcopy(f['request']);result_raw=(f['run']/'result.json').read_bytes();physical_raw=(f['run']/'physics_inputs.json').read_bytes()
        absent=object()
        for value in (bad,None,True,3.0,'3',[],{},absent):
            bundle=copy.deepcopy(original)
            if value is absent:bundle.pop(field)
            else:bundle[field]=value
            write(f['run']/'pose_source.json',bundle);bundle_raw=(f['run']/'pose_source.json').read_bytes()
            request['pose_source_hash']=compat.sha(bundle_raw);write(f['run']/'request.json',request)
            with self.subTest(field=field,value=repr(value)),self.assertRaisesRegex(ValueError,'Consumed input3 format/scheme/raw key mismatch'):compat.source(f['root'],f['current'],f['wanted'])
            self.assertEqual((f['run']/'pose_source.json').read_bytes(),bundle_raw)
            self.assertEqual((f['run']/'result.json').read_bytes(),result_raw);self.assertEqual((f['run']/'physics_inputs.json').read_bytes(),physical_raw)
    def test_input3_request_simulation_key_is_bound_to_physical_raw(self):
        self._request_binding_counterexamples('simulation_key','0'*64)
    def test_input3_request_key_scheme_is_bound_to_physical_raw(self):
        self._request_binding_counterexamples('key_scheme','wrong_scheme')
    def test_input3_saved_bundle_format_is_exactly_integer3(self):
        self._saved_binding_counterexamples('input_format_version',2)
    def test_input3_saved_bundle_simulation_key_is_bound_to_physical_raw(self):
        self._saved_binding_counterexamples('simulation_key','0'*64)
    def test_input3_saved_bundle_key_scheme_is_bound_to_physical_raw(self):
        self._saved_binding_counterexamples('key_scheme','wrong_scheme')
    def test_core_uses_input3_only_for_periodic_and_preserves_pending_on_invalid_input(self):
        jobs=Jobs(self.root/'jobs');sim=dict(count=1,width=2,depth=2,seconds=2,seed=1,edges='walls');bake=dict(resolution=64,height_min=0,height_max=2,normal='OpenGL',samples=1)
        jobs.prepare(MESH,sim,bake);old=jobs.active
        self.assertEqual(old['physics_input_format_version'],2);self.assertEqual(old['physics_contract_version'],2);self.assertEqual(old['bake_contract_version'],2)
        physical=Path(old['physics_inputs_path']).read_bytes()
        self.assertEqual(physical,compat.encoded(compat.inputs(old['assets'],sim,version=2)))
        jobs.prepare(MESH,dict(sim,edges='periodic'),bake);active=jobs.active;pending=copy.deepcopy(jobs._host_pending)
        self.assertEqual({k:active[k] for k in compat.VERSIONS},compat.PERIODIC_VERSIONS)
        raw=Path(active['physics_inputs_path']).read_bytes();self.assertEqual(active['simulation_key'],compat.simulation_key(compat.sha(raw),3))
        self.assertEqual(json.loads(raw)['periodic'],compat.PERIODIC);self.assertEqual(active['periodic'],compat.PERIODIC)
        with self.assertRaises(ValueError):jobs.prepare(MESH,dict(sim,edges='periodic',width=True),bake)
        self.assertIs(jobs.active,active);self.assertEqual(jobs._host_pending,pending)
        self.assertEqual(Path(old['physics_inputs_path']).read_bytes(),physical)
    def test_core_periodic_saved_keeps_original_raw_and_origin_with_bake_changes(self):
        fixture=synthetic_current(self.root,negative_zero=True);jobs=Jobs(self.root)
        pointer=dict(job_id=fixture['current']['job_id'],result_path=str(fixture['run']/'result.json'),files={},request=fixture['request'],result=fixture['result'])
        write(self.root/'current.json',pointer);before=(self.root/'current.json').read_bytes()
        bake=dict(resolution=128,height_min=-1,height_max=3,normal='DirectX',samples=2)
        jobs.prepare(fixture['request']['assets'],fixture['request']['simulation'],bake,rebake=True,host_mode='saved_input')
        active=jobs.active;bundle=json.loads(Path(active['pose_source_path']).read_bytes())
        self.assertEqual(active['operation'],'bake');self.assertEqual({k:active[k] for k in compat.VERSIONS},compat.PERIODIC_VERSIONS)
        self.assertEqual(Path(active['physics_inputs_path']).read_bytes(),fixture['physical_raw'])
        self.assertEqual(bundle['poses'],fixture['result']['poses']);self.assertEqual(bundle['origin'],fixture['result']['pose_origin'])
        self.assertEqual(active['simulation_key'],fixture['request']['simulation_key'])
        pending=copy.deepcopy(jobs._host_pending)
        with self.assertRaises(ValueError):jobs.prepare(fixture['request']['assets'],dict(fixture['request']['simulation'],width=3),bake,rebake=True,host_mode='saved_input')
        self.assertIs(jobs.active,active);self.assertEqual(jobs._host_pending,pending);self.assertEqual((self.root/'current.json').read_bytes(),before)

if __name__=='__main__':unittest.main(verbosity=2)
