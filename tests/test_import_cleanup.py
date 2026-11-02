"""Import cleanup deletes only safely owned failed work, never a live import."""
import asyncio
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock,patch
from fastapi import UploadFile
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'local_review'))
import server,import_cleanup

class ImportCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.work=Path(self.tmp.name);self.state=self.work/'assets.json';self.state.write_text('{}',encoding='utf8');self.assets={};self.current={'job_id':'a'*32}
    def tearDown(self):self.tmp.cleanup()
    def contexts(self):
        return patch.multiple(server,WORK=self.work,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current),process=None,runtime_latched=False,task=None,lock=asyncio.Lock())
    def dirs(self):
        p=self.work/'imports';return list(p.iterdir()) if p.exists() else []
    def test_invalid_upload_and_finished_normalize_failure_clean_only_owned_folder(self):
        with self.contexts(),patch.object(server,'space_budget'),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            h={'X-Review-Token':server.TOKEN};r=client.post('/api/assets',headers=h,files={'files':('bad.exe',b'data','application/octet-stream')});self.assertEqual(r.status_code,400);self.assertEqual(self.dirs(),[])
            async def failed(folder,source,settings):
                (folder/'generated').mkdir();(folder/'generated'/'partial').write_text('failed',encoding='utf8');raise ValueError('conversion failed')
            with patch.object(server,'normalize',new=failed):
                r=client.post('/api/assets',headers=h,files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,400);self.assertEqual(self.dirs(),[]);self.assertEqual(self.assets,{});self.assertEqual(self.state.read_text(),'{}');self.assertEqual(self.current,{'job_id':'a'*32})
            async def process_failed(folder,source,settings):raise ValueError('Process failed; see owned stdout/stderr logs')
            with patch.object(server,'normalize',new=process_failed):
                r=client.post('/api/assets',headers=h,files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,400);self.assertIn('temporary import files were cleaned',r.json()['detail']);self.assertNotIn('see owned stdout/stderr logs',r.json()['detail']);self.assertEqual(self.dirs(),[])
    def test_cancel_during_conversion_preserves_unknown_background_work(self):
        async def run():
            started=asyncio.Event()
            async def pending(folder,source,settings):
                (folder/'partial').write_text('background may still run');started.set();await asyncio.Event().wait()
            with self.contexts(),patch.object(server,'space_budget'),patch.object(server,'normalize',new=pending):
                task=asyncio.create_task(server.upload([UploadFile(filename='new.obj',file=io.BytesIO(b'v 0 0 0\n'))],units='m',up_axis='Z',forward_axis='Y',import_mode='auto',parts_mode='group'));await asyncio.wait_for(started.wait(),3);task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                self.assertEqual(len(self.dirs()),1);self.assertTrue((self.dirs()[0]/'partial').exists());self.assertEqual(self.assets,{})
        asyncio.run(run())
    def test_ambiguous_catalog_write_preserves_import(self):
        async def done(folder,source,settings):return [dict(asset_id='b'*32,enabled=True,source=str(source),folder=str(folder),physics=str(source),scale=1,weight=1)]
        def committed_then_error(path,data):path.write_text(json.dumps(data),encoding='utf8');raise OSError('failure after replacement')
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server,'normalize',new=done),patch.object(server,'write',side_effect=committed_then_error),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            r=client.post('/api/assets',headers={'X-Review-Token':server.TOKEN},files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,400);self.assertIn('cleanup unconfirmed, preserved',r.json()['detail']);self.assertEqual(len(self.dirs()),1);self.assertTrue((self.dirs()[0]/'new.obj').exists());self.assertIn('b'*32,json.loads(self.state.read_text()))
    def test_unconfirmed_process_keeps_folder_and_reports_path(self):
        async def failed(folder,source,settings):
            server.runtime_latched=True;raise ValueError('process termination unconfirmed')
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server,'normalize',new=failed),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            r=client.post('/api/assets',headers={'X-Review-Token':server.TOKEN},files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,400);self.assertIn('cleanup unconfirmed, preserved',r.json()['detail']);self.assertEqual(len(self.dirs()),1);self.assertTrue((self.dirs()[0]/'new.obj').exists());self.assertEqual(self.state.read_text(),'{}')
    def test_success_keeps_committed_folder_and_user_data(self):
        async def done(folder,source,settings):return [dict(asset_id='b'*32,name='new.obj',enabled=True,source=str(source),folder=str(folder),physics=str(source),scale=1,weight=1,metadata={})]
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server,'normalize',new=done),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            r=client.post('/api/assets',headers={'X-Review-Token':server.TOKEN},files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(self.dirs()),1);self.assertTrue((self.dirs()[0]/'new.obj').is_file());self.assertIn('b'*32,self.assets);self.assertIn('b'*32,json.loads(self.state.read_text()));self.assertEqual(self.current,{'job_id':'a'*32})
    def test_rejects_foreign_or_non_uuid_directory(self):
        outside=self.work/'keep';outside.mkdir();(outside/'sentinel').write_text('preserve')
        with self.assertRaises(ValueError):import_cleanup.clean(self.work,outside,'f'*32)
        with self.assertRaises(ValueError):import_cleanup.clean(self.work,self.work/'imports'/'notuuid','notuuid')
        self.assertEqual((outside/'sentinel').read_text(),'preserve')

if __name__=='__main__':unittest.main()
