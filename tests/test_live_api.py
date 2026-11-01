"""In-process ASGI with owned synthetic files only; no service/worker/SDK."""
from pathlib import Path
import json,shutil,sys,types,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'local_review'))
from fastapi.testclient import TestClient
import server
from test_live_preview import LivePreview
from substance_physics_scatter import live_preview as L


class LiveAPI(LivePreview):
    def test_normal_GET_active_token_frame_geometry_and_cancel_boundaries(self):
        a=self.request['assets'][0];target=self.run/'inputs/review-assets'/a['asset_id']/'physics.obj';target.parent.mkdir(parents=True);shutil.copyfile(a['path'],target);a['path']=str(target)
        (self.run/'request.json').write_text(json.dumps(self.request),encoding='utf8')
        d=L.begin(self.jobs,self.request,self.token,self.exe,'normal');L.heartbeat(self.jobs,self.token,1234);d=L.registration(self.jobs,'normal');self.write_frame(self.frame(d,4))
        jobs=types.SimpleNamespace(directory=self.jobs,active=self.request)
        with patch.object(server,'jobs',jobs),patch.object(server,'run_state',dict(status='running',token=self.token)),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',45000)) as client:
            state=client.get('/api/live-state').json();self.assertEqual(state['status'],'running');self.assertEqual(state['frame']['step'],4)
            geometry=client.get(state['assets'][0]['geometry_url']);self.assertEqual(geometry.status_code,400);self.assertIn('triangles',geometry.json()['detail']) # TEST_ONLY cube is deliberately quads; no fake triangulation.
            bad=client.get('/api/live/geometry',params=dict(job=d['job_id'],token='f'*32,asset='a'*32));self.assertIn(bad.status_code,(400,404))
            server.run_state['status']='cancelling';cancel=client.get('/api/live-state').json();self.assertEqual(cancel['status'],'cancelled');self.assertIsNone(cancel['frame'])
    def test_Graph_GET_has_fixed_locator_and_no_source_or_result_mutation(self):
        d=self.descriptor();self.write_frame(self.frame(d,8));watch={p:p.read_bytes() for p in (self.run/'request.json',self.run/'physics_inputs.json')}
        with patch.object(server.designer_review,'locator',return_value=(b'',{},self.root,self.jobs)),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',45000)) as client:
            state=client.get('/api/designer-review/live-state').json();self.assertEqual(state['frame']['time'],8/120)
            self.assertTrue(state['assets'][0]['geometry_url'].startswith('/api/designer-review/live/geometry?'))
            self.assertEqual(client.get(state['assets'][0]['geometry_url']).status_code,400) # Unsupported quad fixture is explicit.
            L.finish(self.jobs,self.token,'failed');self.assertEqual(client.get('/api/designer-review/live-state').json()['status'],'failed')
        self.assertEqual(watch,{p:p.read_bytes() for p in watch});self.assertFalse((self.run/'result.json').exists())
    def test_ready_POST_requires_csrf_active_nonce_and_initial_frame(self):
        d=self.descriptor();frame=self.frame(d);frame['ready_status']='waiting';self.write_frame(frame)
        with patch.object(server.designer_review,'locator',return_value=(b'',{},self.root,self.jobs)),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',45000)) as client:
            body=dict(job_id=d['job_id'],token=self.token,sequence=1)
            self.assertEqual(client.post('/api/designer-review/live-ready',json=body).status_code,403)
            headers={'Origin':server.ORIGIN,'X-Review-Token':server.TOKEN}
            self.assertEqual(client.post('/api/designer-review/live-ready',json=dict(body,token='f'*32),headers=headers).status_code,400)
            response=client.post('/api/designer-review/live-ready',json=body,headers=headers);self.assertEqual(response.status_code,200);self.assertTrue(response.json()['acknowledged'])
            self.assertEqual(json.loads((self.run/'live-ready-v1.json').read_bytes()),dict(schema_version=1,job_id=d['job_id'],nonce=self.token,sequence=1))

# Inherited protocol tests already ran in test_live_preview; run only the new routes here.
def load_tests(loader,tests,pattern):
    return unittest.TestSuite(LiveAPI(name) for name in ('test_normal_GET_active_token_frame_geometry_and_cancel_boundaries','test_Graph_GET_has_fixed_locator_and_no_source_or_result_mutation','test_ready_POST_requires_csrf_active_nonce_and_initial_frame'))

if __name__=='__main__':unittest.main()
