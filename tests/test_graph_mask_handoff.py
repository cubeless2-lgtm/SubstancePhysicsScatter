"""Graph mask transport ownership, claim integrity and saved provenance."""
import asyncio
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'local_review'))
sys.path.insert(0,str(ROOT/'plugin'))
from PIL import Image
from fastapi.testclient import TestClient
import graph_mask_handoff as graph
import server

class GraphMaskHandoff(unittest.TestCase):
    def test_concurrent_draft_cas_keeps_one_winner(self):
        asset='a'*32;job='b'*32
        settings=dict(assets=[dict(asset_id=asset,scale=1.0,weight=1.0)],simulation=dict(count=3,width=1.0,depth=1.0,seconds=3.0,seed=1,edges='walls'),bake=dict(resolution=64,height_min=0.0,height_max=2.0,normal='OpenGL',samples=1),mask_id=None)
        assets={asset:dict(enabled=True,render_revision='r',material_revision='m',metadata=dict(files={'physics.obj':'p'}))}
        submission=server.DraftSubmit(settings=settings,expected_revision=None,expected_current_job_id=job,expected_asset_revisions={asset:dict(render_revision='r',material_revision='m',physics_sha256='p')})
        async def run():
            with patch.multiple(server,assets=assets,jobs=types.SimpleNamespace(current={'job_id':job}),designer_draft=None,lock=asyncio.Lock(),draft_lock=asyncio.Lock(),process=None,task=None,runtime_latched=False),patch.object(server,'is_busy',return_value=False):
                result=await asyncio.gather(server.set_designer_draft(submission),server.set_designer_draft(submission),return_exceptions=True)
                winners=[x for x in result if isinstance(x,dict)];losers=[x for x in result if isinstance(x,server.HTTPException)]
                self.assertEqual(len(winners),1);self.assertEqual(len(losers),1);self.assertEqual(losers[0].status_code,409)
                self.assertEqual(server.designer_draft['revision'],winners[0]['revision'])
        asyncio.run(run())

    def test_draft_revision_rejects_settings_asset_and_current_changes(self):
        asset='a'*32;job='b'*32
        body=dict(assets=[dict(asset_id=asset,scale=1.0,weight=1.0)],simulation=dict(count=3,width=1.0,depth=1.0,seconds=3.0,seed=1,edges='walls'),bake=dict(resolution=64,height_min=0.0,height_max=2.0,normal='OpenGL',samples=1),mask_id=None)
        assets={asset:dict(enabled=True,render_revision='r',material_revision='m',metadata=dict(files={'physics.obj':'p'}))}
        jobs=types.SimpleNamespace(current={'job_id':job})
        with patch.object(server,'assets',assets),patch.object(server,'jobs',jobs),patch.object(server,'designer_draft',None),patch.object(server,'is_busy',return_value=False),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            h={'X-Review-Token':server.TOKEN}
            revision={asset:dict(render_revision='r',material_revision='m',physics_sha256='p')}
            wrapped=dict(settings=body,expected_revision=None,expected_current_job_id=job,expected_asset_revisions=revision)
            r=client.post('/api/designer-draft',headers=h,json=wrapped);self.assertEqual(r.status_code,200,r.text);draft=r.json()
            self.assertEqual(client.get('/api/designer-draft').json()['revision'],draft['revision'])
            # Another view using its stale prior snapshot cannot replace or delete the winner.
            self.assertEqual(client.post('/api/designer-draft',headers=h,json=wrapped).status_code,409)
            self.assertEqual(client.delete('/api/designer-draft/'+'d'*32,headers=h).status_code,409)
            self.assertEqual(client.get('/api/designer-draft').json()['revision'],draft['revision'])
            stale_current=dict(wrapped,expected_revision=draft['revision'],expected_current_job_id='f'*32)
            self.assertEqual(client.post('/api/designer-draft',headers=h,json=stale_current).status_code,409)
            stale_asset=dict(wrapped,expected_revision=draft['revision'],expected_asset_revisions={asset:dict(revision[asset],material_revision='stale')})
            self.assertEqual(client.post('/api/designer-draft',headers=h,json=stale_asset).status_code,409)
            self.assertEqual(client.get('/api/designer-draft').json()['revision'],draft['revision'])
            run=dict(draft['settings'],designer_draft_revision=draft['revision'],expected_current_job_id=job)
            server._draft_guard(server.Run(**run))
            changed=dict(run,simulation=dict(run['simulation'],seed=2))
            with self.assertRaises(ValueError):server._draft_guard(server.Run(**changed))
            assets[asset]['material_revision']='changed'
            with self.assertRaises(ValueError):server._draft_guard(server.Run(**run))
            assets[asset]['material_revision']='m';jobs.current={'job_id':'c'*32}
            with self.assertRaises(ValueError):server._draft_guard(server.Run(**run))
            jobs.current={'job_id':job};client.delete('/api/designer-draft/'+draft['revision'],headers=h)
            with self.assertRaises(ValueError):server._draft_guard(server.Run(**run))

    def test_upload_owned_file_rejects_untrusted_paths_and_corruption(self):
        out=io.BytesIO();Image.new('I;16',(512,512)).save(out,format='PNG');png=out.getvalue()
        sha=hashlib.sha256(png).hexdigest()
        claim=dict(png=dict(sha256=sha,decoded_u16be_sha256='0'*64,width=512,height=512,bit_depth=16,format='LUM16',bytes=len(png)),capture={},operation_authored_payload={})
        def fake_capture(packet):
            self.assertEqual(Path(packet['png']['path']).read_bytes(),png)
            if packet['png']['sha256']!=sha:raise ValueError('bad hash')
        with tempfile.TemporaryDirectory() as tmp, patch.object(server,'WORK',Path(tmp)), patch.object(graph,'_validated_capture',side_effect=fake_capture), TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            headers={'X-Review-Token':server.TOKEN}
            def post(payload):return client.post('/api/graph-mask',headers=headers,files={'file':('mask.png',png,'image/png')},data={'capture_json':json.dumps(payload)})
            response=post(claim);self.assertEqual(response.status_code,200,response.text);data=response.json()
            self.assertEqual(data['sha256'],sha);self.assertEqual(data['provenance_trust'],graph.TRUST)
            side=Path(tmp)/'masks'/(data['mask_id']+'.graph.json')
            self.assertEqual(hashlib.sha256(side.read_bytes()).hexdigest(),data['provenance_sha256'])
            claim['png']['path']='C:/do-not-open.png';self.assertEqual(post(claim).status_code,400)
            claim['png'].pop('path');claim['png']['sha256']='0'*64;self.assertEqual(post(claim).status_code,400)
            self.assertEqual(len(list((Path(tmp)/'masks').glob('*.png'))),1)

    def test_record_binds_job_mode_and_mask(self):
        claim=dict(png=dict(sha256='a'*64,decoded_u16be_sha256='b'*64,width=512,height=512,bit_depth=16,format='LUM16',bytes=10),capture={},operation_authored_payload={})
        raw=json.dumps(claim).encode();request=dict(operation='simulate_bake',scatter_mask=dict(content_hash='a'*64));candidate=dict(job_id='c'*32,request=request)
        with patch.object(graph,'_validated_capture'):
            record=graph.make_job(candidate['job_id'],request,raw,'mask.png','captured')
            with patch.object(graph.maskio,'cache_path',return_value=Path('mask.png')):
                self.assertEqual(graph.verify_job(record,candidate,'jobs')['mode'],'captured')
                candidate['request']['operation']='bake'
                with self.assertRaises(ValueError):graph.verify_job(record,candidate,'jobs')
                candidate['request']['scatter_mask']['content_hash']='d'*64
                with self.assertRaises(ValueError):graph.verify_job(record,candidate,'jobs')

if __name__=='__main__':unittest.main()
