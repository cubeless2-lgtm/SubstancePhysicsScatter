"""Synthetic live protocol + fake UI callbacks only. No actual worker/SDK."""
from pathlib import Path
import ast,copy,json,sys,tempfile,time,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'));sys.path.insert(0,str(ROOT/'local_review'))
from substance_physics_scatter import live_preview as L,motion
from test_periodic_contract import synthetic_current


class LivePreview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.jobs=self.root/'jobs'
        self.fixture=synthetic_current(self.jobs,version=2);self.request=self.fixture['request'];self.run=self.fixture['run'];(self.run/'result.json').unlink()
        self.token='2'*32;self.exe=ROOT/'build-review-live-io1/Release/scatter_worker_legacy_live.exe';L._cache.clear()
    def descriptor(self):
        d=L.begin(self.jobs,self.request,self.token,self.exe,'graph');L.heartbeat(self.jobs,self.token,1234)
        return L.registration(self.jobs,'graph',(self.request['job_id'],self.token))
    def frame(self,d,step=0):
        p=self.fixture['result']['poses'][0]
        return dict(schema_version=1,job_id=d['job_id'],nonce=d['nonce'],process_id=d['pid'],producer=d['producer'],physics_input_hash=d['physics_input_hash'],coordinate_system='RH_Z_UP',units='meters',sequence=step+1,step=step,time=step/120,phase='simulate',bodies=[{k:p[k] for k in ('id','asset_id','scale')}],positions=[p['position']],rotations=[p['rotation']])
    def write_frame(self,f):
        path=self.run/'live-frame-v1.json';temp=self.run/'TEST_ONLY.tmp';temp.write_bytes(json.dumps(f,separators=(',',':')).encode());temp.replace(path)
    def test_registered_latest_frame_job_nonce_pid_producer_and_body_gates(self):
        d=self.descriptor();frame=self.frame(d);self.write_frame(frame)
        state=L.state(self.jobs,'graph',(d['job_id'],d['token']),'/fixed')
        self.assertEqual(state['status'],'running');self.assertEqual(state['sequence'],1)
        self.assertEqual(state['frame']['time'],0);self.assertIn('token='+self.token,state['assets'][0]['geometry_url'])
        original=L.asset(self.jobs,'graph',d['job_id'],d['token'],'a'*32)
        self.assertEqual(motion.digest(original),self.request['assets'][0]['content_hash'])
        for field,value in (('nonce','9'*32),('process_id',99),('physics_input_hash','0'*64),('sequence',False),('time',.1)):
            bad=copy.deepcopy(frame);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):L.validate_frame(json.dumps(bad).encode(),d)
        newer=self.frame(d,4);newer['bodies'][0]['id']=1;self.write_frame(newer)
        self.assertEqual(L.state(self.jobs,'graph',(d['job_id'],d['token']))['status'],'error')
        with self.assertRaises(ValueError):L.asset(self.jobs,'graph',d['job_id'],'f'*32,'a'*32)
    def test_stop_stale_owner_and_request_tamper_never_return_live_frame(self):
        d=self.descriptor();self.write_frame(self.frame(d,4));L.finish(self.jobs,self.token,'cancelled')
        state=L.state(self.jobs,'graph');self.assertEqual(state['status'],'cancelled');self.assertIsNone(state['frame'])
        with self.assertRaises(ValueError):L.asset(self.jobs,'graph',d['job_id'],self.token,'a'*32)
        path=L.descriptor_path(self.jobs);value=motion.decode(L.read(path,65536));value['status']='running';value['pid']=1234;L.atomic(path,value,self.jobs)
        with patch.object(L.time,'time',return_value=time.time()+10):self.assertEqual(L.state(self.jobs,'graph')['status'],'error')
        (self.run/'request.json').write_bytes(b'{}')
        self.assertEqual(L.state(self.jobs,'graph')['status'],'error')
    def test_partial_budget_and_geometry_escape_fail_closed(self):
        d=self.descriptor();path=self.run/'live-frame-v1.json';path.write_bytes(b'{')
        self.assertEqual(L.state(self.jobs,'graph')['status'],'error')
        path.write_bytes(b'x'*(motion.MAX_BYTES+1));self.assertEqual(L.state(self.jobs,'graph')['status'],'error')
        value=motion.decode(L.read(L.descriptor_path(self.jobs),65536));value['assets'][0]['geometry_path']=str(self.root/'outside.obj');L.atomic(L.descriptor_path(self.jobs),value,self.jobs)
        with self.assertRaises(ValueError):L.asset(self.jobs,'graph',d['job_id'],d['token'],'a'*32)
    def test_own_UI_live_callbacks_lazy_fields_and_foreign_process_passthrough(self):
        from types import SimpleNamespace
        tree=ast.parse((ROOT/'plugin/substance_physics_scatter/ui.py').read_text(encoding='utf8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Panel')
        f=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_live_started')
        env=dict(HOST_ERRORS=(Exception,),live_preview=L,QtCore=SimpleNamespace(QTimer=SimpleNamespace(singleShot=lambda *a:None)))
        exec(compile(ast.Module(body=[f],type_ignores=[]),'<actual UI started callback>','exec'),env)
        calls=[];panel=SimpleNamespace(_owns_process=lambda *a:False)
        process=SimpleNamespace(kill=lambda:calls.append('kill'))
        env['_live_started'](panel,{},process);self.assertEqual(calls,[])
        self.assertNotIn('QApplication.processEvents',(ROOT/'plugin/substance_physics_scatter/ui.py').read_text(encoding='utf8'))
    def test_native_optin_pacing_and_atomic_replace_contract_is_observation_only(self):
        source=(ROOT/'worker/live.h').read_text(encoding='utf8')
        self.assertIn('SCATTER_LIVE_PREVIEW',source);self.assertIn('sleep_until',source);self.assertIn('MOVEFILE_REPLACE_EXISTING',source);self.assertIn('retry<25',source);self.assertIn('Win32=',source)
        for forbidden in ('SetPosition','SetRotation','SetLinearVelocity','physics.Update'):self.assertNotIn(forbidden,source)
        # The single bounded ready timeout diagnostic carries no pose payload.
        self.assertEqual(source.count('event("progress"'),1)
        self.assertIn('event("progress",{{"stage","live_viewer_ready_timeout"},{"fraction",0}})',source)
        self.assertIn('if(live_v1::observer)',(ROOT/'worker/main.cpp').read_text(encoding='utf8'))


if __name__=='__main__':unittest.main()
