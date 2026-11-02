"""Conservative cleanup of request-owned failed manual texture uploads."""
import asyncio,copy,io,json,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'local_review'))
import server

class TextureImportCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.work=Path(self.tmp.name);self.state=self.work/'assets.json';self.state.write_text('{}',encoding='utf8');self.aid='a'*32
        self.manifest=self.work/'manifest.json';self.manifest.write_text('{}',encoding='utf8')
        self.asset=dict(asset_id=self.aid,enabled=True,name='fixture',source=str(self.work/'source.obj'),folder=str(self.work),physics=str(self.work/'source.obj'),scale=1.,weight=1.,metadata={'material_ready':True},material_manifest=str(self.manifest),render_revision='r',material_revision='m')
        self.assets={self.aid:copy.deepcopy(self.asset)};self.current={'job_id':'b'*32}
        out=io.BytesIO();Image.new('RGB',(512,512),(17,83,144)).save(out,format='PNG');self.png=out.getvalue()
    def tearDown(self):self.tmp.cleanup()
    def contexts(self):return patch.multiple(server,WORK=self.work,state_path=self.state,assets=self.assets,jobs=SimpleNamespace(current=self.current),process=None,runtime_latched=False,task=None,lock=asyncio.Lock())
    def dirs(self):
        p=self.work/'imports';return list(p.iterdir()) if p.exists() else []
    def test_invalid_and_oversized_uploads_remove_only_own_folder(self):
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server.stored_assets,'stage',side_effect=lambda a,*_:a),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            h={'X-Review-Token':server.TOKEN,'X-Asset-Revision':server.identity(self.asset)};url='/api/assets/'+self.aid+'/textures'
            for filename,raw in (('bad.txt',b'x'),('bad.png',b'bad'),('large.png',b'x'*(8*1024*1024+1))):
                r=client.post(url,headers=h,files={'files':(filename,raw,'application/octet-stream')});self.assertEqual(r.status_code,400,r.text);self.assertEqual(self.dirs(),[])
            self.assertEqual(self.assets[self.aid],self.asset);self.assertEqual(self.state.read_text(),'{}');self.assertEqual(self.current,{'job_id':'b'*32})
    def test_cancellation_during_conversion_preserves_folder_until_thread_finishes(self):
        entered=threading.Event();release=threading.Event();done=threading.Event()
        def conversion(source,out,*args):
            try: (out/'thread-running').write_text('preserve');entered.set();release.wait(5);return {'textures':[]}
            finally:done.set()
        async def run():
            with self.contexts(),patch.object(server,'space_budget'),patch.object(server.stored_assets,'stage',side_effect=lambda a,*_:a),patch.object(server.import_contract,'prepare_images',side_effect=conversion):
                task=asyncio.create_task(server.upload_textures(self.aid,[UploadFile(filename='x.png',file=io.BytesIO(self.png))],server.identity(self.asset)))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait,3));task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                    self.assertEqual(len(self.dirs()),1);self.assertTrue((self.dirs()[0]/'canonical'/'thread-running').is_file());self.assertEqual(self.assets[self.aid],self.asset)
                finally:release.set();await asyncio.to_thread(done.wait,5)
        asyncio.run(run())
    def test_completed_conversion_failure_cleans_owned_folder(self):
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server.stored_assets,'stage',side_effect=lambda a,*_:a),patch.object(server.import_contract,'prepare_images',side_effect=ValueError('conversion failed')),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            h={'X-Review-Token':server.TOKEN,'X-Asset-Revision':server.identity(self.asset)};r=client.post('/api/assets/'+self.aid+'/textures',headers=h,files={'files':('x.png',self.png,'image/png')})
            self.assertEqual(r.status_code,400,r.text);self.assertEqual(self.dirs(),[]);self.assertEqual(self.assets[self.aid],self.asset);self.assertEqual(self.current,{'job_id':'b'*32})
    def test_ambiguous_catalog_promotion_preserves_folder(self):
        def committed_then_error(path,value):path.write_text(json.dumps(value),encoding='utf8');raise OSError('after replacement')
        with self.contexts(),patch.object(server,'space_budget'),patch.object(server.stored_assets,'stage',side_effect=lambda a,*_:a),patch.object(server.import_contract,'prepare_images',return_value={'textures':[]}),patch.object(server.texture_revision,'library'),patch.object(server,'write',side_effect=committed_then_error),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',1234)) as client:
            h={'X-Review-Token':server.TOKEN,'X-Asset-Revision':server.identity(self.asset)};r=client.post('/api/assets/'+self.aid+'/textures',headers=h,files={'files':('x.png',self.png,'image/png')})
            self.assertEqual(r.status_code,400,r.text);self.assertIn('cleanup unconfirmed, preserved',r.json()['detail']);self.assertEqual(len(self.dirs()),1);self.assertTrue(any(self.dirs()[0].glob('manual_*.png')));self.assertEqual(self.assets[self.aid],self.asset);self.assertEqual(self.current,{'job_id':'b'*32})

if __name__=='__main__':unittest.main()
