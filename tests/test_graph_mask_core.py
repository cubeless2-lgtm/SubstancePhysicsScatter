"""Core host transaction tests. Synthetic handoffs/candidates are not SDK or native physics evidence."""
import copy,hashlib,json,shutil,struct,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import core,mask_source as source,graph_companion as companion,maskio
from test_mask_decoder import png

class GraphCore(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='scatter_graph_core_한글 ');self.base=Path(self.temp.name)
        self.jobs=core.Jobs(self.base/'jobs');self.image=self.base/'terminal.png'
        self.rows=[dict(asset_id='a'*32,path=str(ROOT/'tests/fixtures/cube.obj'),format='obj',scale=.25,weight=1.)]
        self.sim=dict(count=20,width=2,depth=2,seconds=2,seed=123456789,edges='walls')
        self.bake=dict(resolution=64,height_min=0,height_max=8,normal='OpenGL',samples=1)
        self.package=self.base/'Source.sbs';self.package.write_bytes(b'synthetic core source; no SDK')
        selected=dict(package_path=str(self.package),package_uid=str(uuid.uuid4()),graph_identifier='CoreFixture',terminal_identifier='mask')
        manifest=dict(fixture='synthetic core handoff, not SDK proof')
        payload=dict(schema_version=1,registry_authored_manifest=manifest,registry_authored_sha256=source.signature(manifest),producer_evidence_sha256='a'*64)
        signature=source.signature(payload)
        context=dict(selected,graph_url='pkg:///CoreFixture?dependency=1',terminal_node_id='2',output_id='mask',session_token=uuid.uuid4().hex,loaded_inventory_sha256=source.signature([selected]),authored_sha256=signature)
        self.record=dict(designer_version='synthetic-core-fixture',selection=selected,context=context,pre_authored_sha256=signature,post_authored_sha256=signature,package_modified=False,disk_file_sha256=core.digest(self.package),captured_at='2026-10-31T00:00:00+00:00')
        self.payload=payload;self.packet=self.packet_for(32768)
    def tearDown(self):self.temp.cleanup()
    def packet_for(self,value):
        pixels=struct.pack('>H',value)*512*512
        self.image.write_bytes(png((b'\0'+struct.pack('>H',value)*512)*512,w=512,h=512,bits=16))
        descriptor=dict(path=str(self.image),sha256=core.digest(self.image),decoded_u16be_sha256=hashlib.sha256(pixels).hexdigest(),width=512,height=512,bit_depth=16,format='LUM16',bytes=self.image.stat().st_size)
        return dict(png=descriptor,capture=copy.deepcopy(self.record),operation_authored_payload=copy.deepcopy(self.payload))
    def prepare(self,**kwargs):return self.jobs.prepare(self.rows,self.sim,self.bake,**kwargs)
    def graph(self,packet=None):return self.prepare(host_mode='current_graph_terminal',captured_mask=packet or self.packet)
    def host_candidate(self):
        # Bookkeeping-only fixture; no native validate/physics success is claimed.
        request=copy.deepcopy(self.jobs.active);candidate=dict(job_id=request['job_id'],request=request)
        ref=self.jobs._host_pending[request['job_id']]
        if ref is not None:candidate[companion.KEY]=copy.deepcopy(ref)
        return candidate
    def test_capture_cache_and_host_reference_do_not_change_native_identity(self):
        path=self.graph();request=self.jobs.active
        self.assertEqual(request['scatter_mask']['content_hash'],self.packet['png']['sha256'])
        self.assertEqual(core.digest(request['scatter_mask']['path']),self.packet['png']['sha256'])
        self.assertEqual(Path(request['scatter_mask']['path']).read_bytes(),self.image.read_bytes())
        self.assertNotIn(companion.KEY,request);self.assertNotIn('capture',request)
        candidate=self.host_candidate();doc=companion.read(self.jobs.directory,candidate)
        self.assertEqual(doc['record']['capture'],self.record)
        self.assertEqual(doc['record']['snapshot_sha256'],self.packet['png']['sha256'])
        second=core.Jobs(self.base/'file');second.prepare(self.rows,self.sim,self.bake,scatter_mask=self.image)
        self.assertEqual(second.active['physics_input_hash'],request['physics_input_hash'])
        self.assertEqual(second.active['simulation_key'],request['simulation_key'])
        self.assertEqual(json.loads(path.read_text())['scatter_mask'],request['scatter_mask'])
    def test_new_pixels_with_same_authored_signature_are_not_replaced_by_old_cache(self):
        self.graph();old=self.jobs.active['scatter_mask']['content_hash'];old_job=self.jobs.active['job_id']
        fresh=self.packet_for(16384);self.graph(fresh)
        self.assertNotEqual(self.jobs.active['scatter_mask']['content_hash'],old)
        self.assertNotIn(old_job,self.jobs._host_pending)
        self.assertEqual(self.jobs.active['scatter_mask']['content_hash'],fresh['png']['sha256'])
    def test_bad_handoff_fields_hash_type_and_nonplain_values_reject_before_preparation(self):
        changes=[lambda p:p['png'].update(width=True),lambda p:p['png'].update(bytes=p['png']['bytes']+1),lambda p:p['png'].update(sha256='0'*64),lambda p:p['operation_authored_payload'].update(schema_version=True),lambda p:p['operation_authored_payload']['registry_authored_manifest'].update(other=1),lambda p:p['operation_authored_payload']['registry_authored_manifest'].update(value=(1,2)),lambda p:p.update(wrapper=object()),lambda p:p['capture'].update(package_modified=1)]
        for change in changes:
            bad=copy.deepcopy(self.packet);change(bad)
            with self.subTest(change=change),self.assertRaises(ValueError):self.graph(bad)
        self.assertIsNone(self.jobs.active);self.assertEqual(self.jobs._host_pending,{})
        self.assertEqual(list(self.jobs.directory.iterdir()),[])
    def test_copy_time_pixel_change_is_rejected_and_old_active_pending_preserved(self):
        self.prepare();old=self.jobs.active;pending=copy.deepcopy(self.jobs._host_pending);original=maskio.snapshot
        def changed(*args):
            self.packet_for(16384);return original(*args)
        with patch.object(maskio,'snapshot',side_effect=changed),self.assertRaisesRegex(ValueError,'Capture/cache SHA'):self.graph()
        self.assertIs(self.jobs.active,old);self.assertEqual(self.jobs._host_pending,pending)
    def test_companion_failure_before_and_after_write_keeps_old_active_and_current(self):
        self.prepare();old=self.jobs.active;pending=copy.deepcopy(self.jobs._host_pending)
        previous=self.host_candidate();core.atomic_json(self.jobs.directory/'current.json',previous);current=(self.jobs.directory/'current.json').read_bytes()
        writer=companion.write
        for after in (False,True):
            def failed(*args,**kwargs):
                if after:writer(*args,**kwargs)
                raise OSError('deliberate companion preparation failure')
            with patch.object(companion,'write',side_effect=failed),self.assertRaises(OSError):self.graph()
            self.assertIs(self.jobs.active,old);self.assertEqual(self.jobs._host_pending,pending)
            self.assertEqual((self.jobs.directory/'current.json').read_bytes(),current)
    def test_none_registered_missing_null_and_pointer_mutation_are_distinct(self):
        self.prepare();candidate=self.host_candidate();self.jobs._verify_host(candidate)
        with self.assertRaises(ValueError):self.jobs._verify_host(dict(candidate,**{companion.KEY:None}))
        pointer=self.jobs._host_pending.pop(candidate['job_id'])
        with self.assertRaisesRegex(ValueError,'missing'):self.jobs._verify_host(candidate)
        self.jobs._host_pending[candidate['job_id']]=pointer
        self.graph();candidate=self.host_candidate();candidate[companion.KEY]['sha256']='0'*64
        with self.assertRaises(ValueError):self.jobs.promote(candidate)
        self.assertIsNotNone(self.jobs.active)
    def test_promotion_rechecks_companion_and_atomic_failure_keeps_pending(self):
        self.prepare();self.jobs.promote(self.host_candidate());previous_current=(self.jobs.directory/'current.json').read_bytes()
        self.graph();candidate=self.host_candidate();self.jobs._verify_host(candidate)
        path=Path(self.jobs.active['output_directory'])/companion.NAME;raw=path.read_bytes();pending=copy.deepcopy(self.jobs._host_pending)
        path.write_bytes(raw+b' ')
        with self.assertRaises(ValueError):self.jobs.promote(candidate)
        self.assertEqual((self.jobs.directory/'current.json').read_bytes(),previous_current);self.assertEqual(self.jobs._host_pending,pending)
        path.write_bytes(raw)
        with patch.object(core,'atomic_json',side_effect=OSError('deliberate atomic write failure')),self.assertRaises(OSError):self.jobs.promote(candidate)
        self.assertEqual(self.jobs._host_pending,pending);self.assertIsNotNone(self.jobs.active)
        self.assertEqual((self.jobs.directory/'current.json').read_bytes(),previous_current)
        self.jobs.promote(candidate);self.assertIsNone(self.jobs.active);self.assertEqual(self.jobs._host_pending,{})
        self.assertIn(companion.KEY,self.jobs.current)
    def test_active_replacement_late_result_and_cancel_only_current_pending(self):
        self.graph();old=self.host_candidate();old_active=self.jobs.active;pending=copy.deepcopy(self.jobs._host_pending)
        bad=copy.deepcopy(self.packet);bad['png']['sha256']='0'*64
        with self.assertRaises(ValueError):self.graph(bad)
        self.assertIs(self.jobs.active,old_active);self.assertEqual(self.jobs._host_pending,pending)
        self.prepare();new=self.jobs.active['job_id'];self.assertNotIn(old['job_id'],self.jobs._host_pending)
        with self.assertRaises(ValueError):self.jobs.validate(Path('unused'),old['job_id'])
        with self.assertRaises(ValueError):self.jobs.promote(old)
        self.jobs.cancel();self.assertIn(new,self.jobs.cancelled);self.assertIsNone(self.jobs.active);self.assertEqual(self.jobs._host_pending,{})
    def test_invalid_modes_and_graph_to_file_rebake_have_no_preparation_effect(self):
        self.graph();self.jobs.promote(self.host_candidate());before={str(p):core.digest(p) for p in self.jobs.directory.rglob('*') if p.is_file()}
        for kwargs in (dict(host_mode='bad'),dict(captured_mask=self.packet),dict(host_mode='current_graph_terminal',captured_mask=self.packet,scatter_mask=self.image),dict(host_mode='saved_input'),dict(rebake=True,scatter_mask=self.image)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.prepare(**kwargs)
        self.assertEqual(before,{str(p):core.digest(p) for p in self.jobs.directory.rglob('*') if p.is_file()})
    def test_saved_selects_only_owned_snapshot_and_current_survives_move(self):
        self.graph();self.jobs.promote(self.host_candidate());old_root=self.jobs.directory
        moved=self.base/'moved';shutil.copytree(old_root,moved);self.jobs=core.Jobs(moved)
        self.image.write_bytes(b'external source is present again and damaged');current=self.jobs.current
        self.assertTrue(Path(current['request']['scatter_mask']['path']).is_relative_to(moved))
        class ReachedNativeCompatibility(Exception):pass
        observed=[]
        def reached(root,previous,physical):observed.append(physical);raise ReachedNativeCompatibility()
        with patch.object(core.compat,'source',side_effect=reached),self.assertRaises(ReachedNativeCompatibility):self.prepare(host_mode='saved_input',rebake=True)
        self.assertEqual(observed[0]['scatter_mask']['content_hash'],self.packet['png']['sha256']);self.assertIsNone(self.jobs.active)
        owned=maskio.cache_path(moved,self.packet['png']['sha256']);owned.write_bytes(b'damaged snapshot')
        with self.assertRaises(ValueError):self.prepare(host_mode='saved_input',rebake=True)
    def test_nonplain_authored_values_cannot_pass_by_recomputing_their_json_hashes(self):
        for value in ((1,2),{1:'coercible integer key'},float('nan')):
            bad=copy.deepcopy(self.packet);payload=bad['operation_authored_payload'];payload['registry_authored_manifest']['value']=value
            if not isinstance(value,float):
                payload['registry_authored_sha256']=source.signature(payload['registry_authored_manifest']);signature=source.signature(payload)
                bad['capture']['context']['authored_sha256']=signature;bad['capture']['pre_authored_sha256']=signature;bad['capture']['post_authored_sha256']=signature
            with self.subTest(value=value),self.assertRaises(ValueError):self.graph(bad)
        self.assertEqual(list(self.jobs.directory.iterdir()),[])
    def test_plain_file_simulation_does_not_inherit_previous_graph_companion(self):
        self.graph();self.jobs.promote(self.host_candidate());old=self.jobs.current[companion.KEY]
        self.prepare();candidate=self.host_candidate();self.assertNotIn(companion.KEY,candidate)
        self.jobs.promote(candidate);self.assertNotIn(companion.KEY,self.jobs.current)
        self.assertEqual(old['schema_version'],2)

if __name__=='__main__':unittest.main()
