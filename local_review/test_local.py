"""Focused pure/ASGI/fake-owned-process tests. Blender/native worker/browser are never run."""
import asyncio,copy,json,sys,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import server as s

class Review(unittest.TestCase):
    def setUp(self):
        self.root=s.BASE/'test-output'/uuid.uuid4().hex;self.root.mkdir(parents=True)
        self.patches=[patch.object(s,'WORK',self.root),patch.object(s,'assets',{}),patch.object(s,'state_path',self.root/'assets.json'),patch.object(s,'lock',asyncio.Lock()),patch.object(s,'task',None),patch.object(s,'process',None),patch.object(s,'run_state',dict(status='idle',token=None,events=[],error=None)),patch.object(s,'jobs',type('Empty',(),{'current':None})())]
        for p in self.patches:p.start()
        self.client=TestClient(s.app,base_url=s.ORIGIN,client=('127.0.0.1',45000));self.headers={'X-Review-Token':s.TOKEN,'Origin':s.ORIGIN}
    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches):p.stop()
    def test_host_origin_and_mutation_token(self):
        self.assertEqual(self.client.get('/api/state').status_code,200)
        self.assertEqual(self.client.get('/api/state',headers={'Host':'evil.local'}).status_code,403)
        self.assertEqual(self.client.get('/api/state',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/cancel/'+'a'*32).status_code,403)
        self.assertEqual(self.client.post('/api/cancel/'+'a'*32,headers=self.headers).status_code,409)
        html=self.client.get('/');self.assertEqual(html.status_code,200);self.assertIn('frame-ancestors',html.headers['content-security-policy']);self.assertIn('nonce="'+s.TOKEN+'"',html.text)
        policy=html.headers['content-security-policy'];connect=next(x.strip() for x in policy.split(';') if x.strip().startswith('connect-src '));self.assertEqual(connect,"connect-src 'self' blob:");self.assertNotIn('https:',connect);self.assertNotIn('*',connect)
        self.assertIn('미지원',html.text);self.assertEqual(self.client.get('/vendor/three/build/three.module.js').status_code,200)
    def test_upload_paths_dependency_and_budget(self):
        for name in ('../x.obj','C:x.obj','a/b.obj','NUL.obj','.hidden.obj','x.obj '):
            with self.subTest(name=name),self.assertRaises(ValueError):s.safe_name(name)
        folder=self.root/'bundle';folder.mkdir();obj=folder/'one.obj';obj.write_text('mtllib ../outside.mtl\n',encoding='utf-8')
        with self.assertRaises(ValueError):s.bundle_links(folder,obj)
        obj.write_text('mtllib missing.mtl\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Missing'):s.bundle_links(folder,obj)
        obj.write_text('v 0 0 0\n',encoding='utf-8');s.bundle_links(folder,obj)
        with self.assertRaises(ValueError):s.owned(self.root.parent/'unowned.obj')
        self.assertEqual(self.client.post('/api/assets',headers={**self.headers,'Content-Length':str(s.MAX_UPLOAD*2)}).status_code,413)
    def test_settings_and_unsupported_capabilities(self):
        data=dict(assets=[dict(asset_id='a'*32,scale=.25,weight=1.)],simulation={},bake={})
        self.assertEqual(s.Run.model_validate(data).simulation.count,40)
        for change in (dict(count=True),dict(seed=-1),dict(width=float('nan')),dict(seconds=121)):
            with self.subTest(change=change),self.assertRaises(ValueError):s.Run.model_validate(dict(data,simulation=change))
        state=self.client.get('/api/state').json()
        self.assertTrue(state['capabilities']['hull']);self.assertTrue(state['capabilities']['fbx']);self.assertTrue(state['capabilities']['pbr_bake']);self.assertEqual(state['capabilities']['selected_asset_limit'],6)
    def test_queued_job_blocks_mutation_and_stale_cancel(self):
        future=type('Pending',(),{'done':lambda self:False})();s.task=future;s.assets['a'*32]={'enabled':True}
        self.assertEqual(self.client.delete('/api/assets/'+'a'*32,headers=self.headers).status_code,409)
        self.assertEqual(self.client.post('/api/cancel/'+'b'*32,headers=self.headers).status_code,409)

    def execution(self,failure=None,cancelled=False):
        jobsroot=self.root/'jobs';jobsroot.mkdir();current=jobsroot/'current.json';current.write_bytes(b'last-good-fixture')
        physics=self.root/'fixture.obj';physics.write_text('# test-only owned input',encoding='utf-8');glb=self.root/'scene.glb';glb.write_bytes(b'glTF-test-only-bookkeeping');aid='a'*32;s.assets[aid]=dict(enabled=True,physics=str(physics),folder=str(self.root),metadata=dict(files={'scene.glb':s.sha(glb)}))
        token='b'*32;job='c'*32;calls=[]
        class FakeJobs:
            def prepare(self,*args,**kwargs):
                calls.append('prepare');self.active={'job_id':job,'assets':[dict(asset_id=aid,content_hash=s.sha(physics))]};path=jobsroot/'runs'/job/'request.json';path.parent.mkdir(parents=True);path.write_text('{}');return path
            def validate(self,*args):calls.append('validate');return dict(job_id=job,request=self.active)
            def promote(self,candidate):
                calls.append('promote')
                if failure=='promote':raise OSError('atomic promotion sentinel')
                current.write_text(json.dumps(candidate),encoding='utf-8')
            def cancel(self):calls.append('cancel');self.active=None
        async def bounded(*args,**kwargs):
            calls.append('worker_fake')
            if failure=='worker':raise ValueError('worker sentinel')
            if failure=='stale':s.run_state['token']='d'*32
            return [dict(job_id=job,event='completed')]
        s.jobs=FakeJobs();s.run_state=dict(status='cancelling' if cancelled else 'queued',token=token,events=[],error=None)
        body=s.Run.model_validate(dict(assets=[dict(asset_id=aid,scale=.25,weight=1.)],simulation={},bake={}))
        def seal(records,request,work,check_space):
            request=copy.deepcopy(request);request['review_v1']={'bake_pbr':False};return request,dict(path='fake-bookkeeping',sha256='f'*64),dict(renders={aid:dict(glb_path=str(glb),glb_sha256=s.sha(glb))},pbr_unavailable=['TEST_ONLY geometry bookkeeping'])
        with patch.object(s,'bounded',bounded),patch.object(s.job_assets,'seal',seal),patch.object(s.job_assets,'verify',return_value=None),patch.object(s.result_bundle,'get',return_value={}):asyncio.run(s.execute(body,token))
        return current,calls
    def test_failure_and_cancel_preserve_lastgood(self):
        path,calls=self.execution('worker');self.assertEqual(path.read_bytes(),b'last-good-fixture');self.assertIn('worker_fake',calls);self.assertNotIn('promote',calls);self.assertTrue(s.run_state['last_good_preserved'])
    def test_atomic_promotion_failure_preserves_lastgood(self):
        path,calls=self.execution('promote');self.assertEqual(path.read_bytes(),b'last-good-fixture');self.assertIn('promote',calls);self.assertTrue(s.run_state['last_good_preserved'])
    def test_cancel_before_prepare_starts_no_worker(self):
        path,calls=self.execution(cancelled=True);self.assertEqual(calls,['cancel']);self.assertEqual(s.run_state['status'],'cancelled')
    def test_success_metadata_is_in_same_promoted_transaction(self):
        path,calls=self.execution();record=json.loads(path.read_text());self.assertIn('local_review',record);self.assertEqual(s.run_state['status'],'completed');self.assertFalse((self.root/'result-settings.json').exists())
    def test_late_completed_token_is_discarded(self):
        path,calls=self.execution('stale');self.assertEqual(path.read_bytes(),b'last-good-fixture');self.assertNotIn('promote',calls);self.assertTrue(s.run_state['last_good_preserved'])
    def test_display_conversion_and_scale_are_applied_once(self):
        import numpy as np
        c=np.array([[1,0,0],[0,0,1],[0,-1,0]],dtype=float);point=np.array([.5,-.2,.4]);translation=np.array([1.,2.,3.]);q=np.array([[0,-1,0],[1,0,0],[0,0,1]],dtype=float);scale=.25
        gltf=c@point;rendered=c@(translation+q@(scale*(c.T@gltf)));expected=c@(translation+q@(scale*point));self.assertTrue(np.array_equal(rendered,expected))
        js=(s.BASE/'web/app.js').read_text(encoding='utf8');self.assertIn('world.rotation.x=-Math.PI/2',js);self.assertIn('local.rotation.x=Math.PI/2',js);self.assertEqual(js.count('pose.scale.setScalar(entry.pose.scale)'),1)
        script=(s.BASE/'convert_asset.py').read_text(encoding='utf8');self.assertIn("mesh=obj.data",script);self.assertIn('mesh.loop_triangles',script);self.assertIn("export_yup=True",script)

    def test_actual_process_boundary_with_fake_owned_handle(self):
        async def exercise(cancel=False,overflow=False):
            class Pipe:
                def __init__(self,data):self.data=data
                async def read(self,n):data=self.data;self.data=b'';return data
            class Proc:
                def __init__(self):self.stdout=Pipe(b'x'*(s.LOG_LIMIT+1) if overflow else b'');self.stderr=Pipe(b'');self.returncode=None if cancel else 0;self.stop=asyncio.Event();self.terminated=0
                async def wait(self):
                    if self.returncode is None:await self.stop.wait()
                    return self.returncode
                def terminate(self):self.terminated+=1;self.returncode=-1;self.stop.set()
                def kill(self):self.terminate()
            proc=Proc()
            async def spawn(*args,**kwargs):self.assertNotIn('shell',kwargs);return proc
            s.run_state=dict(status='cancelling' if cancel else 'running',token='d'*32,events=[])
            with patch.object(asyncio,'create_subprocess_exec',spawn):
                with self.assertRaises((InterruptedError,ValueError)):await s.bounded(['owned.exe','owned.json'],self.root/('cancel' if cancel else 'overflow'),1,{'token':'d'*32})
            self.assertIsNone(s.process)
            if cancel:self.assertEqual(proc.terminated,1)
        asyncio.run(exercise(cancel=True));asyncio.run(exercise(overflow=True))

if __name__=='__main__':unittest.main()
