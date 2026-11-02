"""Revision CAS on material, texture and geometry asset mutations."""
import copy
import tempfile
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'local_review'))
import server

class AssetRevisionAPI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.aid='a'*32
        self.source=self.root/'source.obj';self.source.write_text('# fixture',encoding='utf8')
        self.old=dict(asset_id=self.aid,enabled=True,name='source.obj',source=str(self.source),folder=str(self.root),physics=str(self.source),scale=1.,weight=1.,render_revision='r',material_revision='m',metadata={'material_ready':True,'files':{'physics.obj':'p'}})
        self.assets={self.aid:copy.deepcopy(self.old)};self.current={'job_id':'b'*32};self.state=self.root/'assets.json';self.state.write_text('original catalog',encoding='utf8')
    def tearDown(self):self.temp.cleanup()
    def test_all_mutators_reject_missing_or_stale_before_mutation(self):
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000)) as client:
            headers={'X-Review-Token':server.TOKEN};base='/api/assets/'+self.aid
            cases=[('/normalize',dict(json={})),('/material',dict(json={'factors':{'0':{'roughness_factor':0.5}}})),('/textures',dict(files={'files':('x.png',b'not processed','image/png')}))]
            for path,args in cases:
                with self.subTest(path=path):
                    self.assertEqual(client.post(base+path,headers=headers,**args).status_code,428)
                    self.assertEqual(client.post(base+path,headers={**headers,'X-Asset-Revision':'f'*64},**args).status_code,409)
            self.assertEqual(self.assets[self.aid],self.old);self.assertEqual(self.state.read_text(), 'original catalog');self.assertEqual(self.current,{'job_id':'b'*32})
    def test_two_material_editors_cannot_overwrite_each_other(self):
        revised=dict(self.old,material_revision='new')
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),patch.object(server,'space_budget'),patch.object(server.stored_assets,'stage',side_effect=lambda a,*args:a),patch.object(server.material_revision,'build_revision',return_value=(revised,True)),patch.object(server,'write'),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000)) as client:
            rev=server.public_asset(self.old)['asset_revision'];h={'X-Review-Token':server.TOKEN,'X-Asset-Revision':rev};url='/api/assets/'+self.aid+'/material';body={'factors':{'0':{'roughness_factor':0.5}}}
            first=client.post(url,headers=h,json=body);self.assertEqual(first.status_code,200,first.text);self.assertNotEqual(first.json()['asset_revision'],rev)
            self.assertEqual(client.post(url,headers=h,json=body).status_code,409);self.assertEqual(self.assets[self.aid]['material_revision'],'new');self.assertEqual(self.current,{'job_id':'b'*32})
    def test_stale_delete_cannot_remove_newer_revision_and_keeps_source(self):
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000)) as client:
            old_rev=server.public_asset(self.old)['asset_revision'];self.assets[self.aid]=dict(self.old,material_revision='new')
            url='/api/assets/'+self.aid;headers={'X-Review-Token':server.TOKEN}
            self.assertEqual(client.delete(url,headers=headers).status_code,428)
            self.assertEqual(client.delete(url,headers={**headers,'X-Asset-Revision':old_rev}).status_code,409)
            self.assertTrue(self.assets[self.aid]['enabled']);self.assertEqual(self.state.read_text(),'original catalog')
            new_rev=server.public_asset(self.assets[self.aid])['asset_revision']
            self.assertEqual(client.delete(url,headers={**headers,'X-Asset-Revision':new_rev}).status_code,200)
            self.assertFalse(self.assets[self.aid]['enabled']);self.assertEqual(self.source.read_text(),'# fixture');self.assertEqual(self.current,{'job_id':'b'*32})
    def test_delete_catalog_failure_keeps_asset_enabled(self):
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),patch.object(server,'write',side_effect=OSError('catalog failed')),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000),raise_server_exceptions=False) as client:
            rev=server.public_asset(self.old)['asset_revision'];r=client.delete('/api/assets/'+self.aid,headers={'X-Review-Token':server.TOKEN,'X-Asset-Revision':rev})
            self.assertEqual(r.status_code,500);self.assertEqual(self.assets[self.aid],self.old);self.assertEqual(self.state.read_text(),'original catalog');self.assertEqual(self.source.read_text(),'# fixture')
    def test_new_asset_catalog_failure_preserves_old_catalog_and_current(self):
        fresh=dict(self.old,asset_id='c'*32)
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),patch.object(server,'space_budget'),patch.object(server,'normalize',new=AsyncMock(return_value=[fresh])),patch.object(server,'write',side_effect=OSError('catalog failed')),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000),raise_server_exceptions=False) as client:
            r=client.post('/api/assets',headers={'X-Review-Token':server.TOKEN},files={'files':('new.obj',b'v 0 0 0\n','text/plain')})
            self.assertEqual(r.status_code,500);self.assertEqual(self.assets,{self.aid:self.old});self.assertEqual(self.state.read_text(),'original catalog');self.assertEqual(self.current,{'job_id':'b'*32});self.assertEqual(self.source.read_text(),'# fixture')
    def test_normalize_catalog_failure_does_not_disable_old_asset(self):
        fresh=dict(self.old,asset_id='c'*32)
        with patch.multiple(server,WORK=self.root,state_path=self.state,assets=self.assets,jobs=types.SimpleNamespace(current=self.current)),patch.object(server,'is_busy',return_value=False),patch.object(server,'normalize',new=AsyncMock(return_value=[fresh])),patch.object(server,'write',side_effect=OSError('catalog write failed')),TestClient(server.app,base_url=server.ORIGIN,client=('127.0.0.1',30000),raise_server_exceptions=False) as client:
            rev=server.public_asset(self.old)['asset_revision'];r=client.post('/api/assets/'+self.aid+'/normalize',headers={'X-Review-Token':server.TOKEN,'X-Asset-Revision':rev},json={})
            self.assertEqual(r.status_code,500);self.assertEqual(self.assets,{self.aid:self.old});self.assertEqual(self.state.read_text(),'original catalog');self.assertEqual(self.current,{'job_id':'b'*32})

if __name__=='__main__':unittest.main()
