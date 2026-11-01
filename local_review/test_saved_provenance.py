"""Closed Saved provenance preservation; pure protocol fixtures, no native/API."""
import asyncio,copy,hashlib,importlib.util,io,json,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock,Mock
import server as s,saved_provenance as p,result_bundle,result_export,job_assets,pbr_contract
import test_ui3 as ui3_fixture
BASE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('closed_saved_protocol',BASE.parent/'tests/test_periodic_contract.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

def current(item):return dict(job_id=item['request']['job_id'],request=copy.deepcopy(item['request']),result=copy.deepcopy(item['result']),result_path=str(item['run']/'result.json'))
def native_saved(item,identity):
    item=fixture.saved(item,identity);item['result'].pop('pose_source_hash',None);fixture.write(item['run']/'result.json',item['result']);return item

def watch(item):return {str(item['run']/name):(pbr_contract.sha((item['run']/name).read_bytes()),len((item['run']/name).read_bytes())) for name in ('request.json','result.json','physics_inputs.json')}

class SavedProvenance(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='closed_saved_');self.work=Path(self.temp.name);self.jobs=self.work/'jobs';result_bundle._cache=None
    def tearDown(self):self.temp.cleanup()
    def chain(self):
        first=fixture.synthetic_current(self.jobs,version=2);one=native_saved(first,'2'*32);two=native_saved(one,'3'*32);return one,two
    def preserve(self,one,two,**kwargs):
        with patch.object(result_bundle,'get',return_value=dict(watch=watch(one))):return p.preserve(current(one),two['request'],self.work,kwargs.get('space',lambda *_:None))
    def export(self,item):
        c=current(item);fixture.write(self.jobs/'current.json',c)
        bundle=dict(original={role:b'TEST_ONLY not a native image' for role in result_export.MAPS},watch=watch(item),hulls=None)
        with patch.object(result_bundle,'get',return_value=bundle):return result_export.build(c,self.work)
    def test_actual_Blobs_save_Saved2_and3_closed_export_and_old_bytes_preserved(self):
        one,two=self.chain()
        for old,new,identity in ((one,two,'4'*32),):
            old_files={f:f.read_bytes() for f in old['run'].rglob('*') if f.is_file()}
            with self.assertRaisesRegex(ValueError,'과거 출처 raw'):self.export(new)
            pointer=(self.jobs/'current.json').read_bytes();existing={f:f.read_bytes() for f in new['run'].rglob('*') if f.is_file()};rows=self.preserve(old,new);self.assertTrue(rows);self.assertTrue(all(f.read_bytes()==raw for f,raw in existing.items()))
            self.assertEqual((self.jobs/'current.json').read_bytes(),pointer);self.assertTrue(all(f.read_bytes()==b for f,b in old_files.items()))
            for row in rows:self.assertEqual(pbr_contract.sha(Path(row['path']).read_bytes()),row['sha256'])
            archive=self.export(new)
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                for row in rows:self.assertEqual(z.read('job/'+Path(row['path']).relative_to(new['run']).as_posix()),Path(row['path']).read_bytes())
            third=native_saved(new,identity);old_files={f:f.read_bytes() for f in new['run'].rglob('*') if f.is_file()};self.preserve(new,third);self.export(third);self.assertTrue(all(f.read_bytes()==b for f,b in old_files.items()))
    def test_existing_conflict_missing_and_budget_refuse(self):
        one,two=self.chain();head=json.loads((two['run']/'pose_source.json').read_bytes());older=json.loads((one['run']/'pose_source.json').read_bytes());h=older['source_request_sha256'];target=two['run']/'provenance'/(h+'.json');self.assertFalse(target.exists())
        target.write_bytes(b'CONFLICT')
        with self.assertRaisesRegex(ValueError,'SHA conflict'):self.preserve(one,two)
        target.unlink();source=one['run']/'provenance'/(h+'.json');raw=source.read_bytes();source.unlink()
        with self.assertRaisesRegex(ValueError,'이전 job에도'):self.preserve(one,two)
        source.write_bytes(raw)
        for cap,value in (('BYTE_CAP',1),('COUNT_CAP',1),('DEPTH_CAP',0)):
            with self.subTest(cap=cap),patch.object(p,cap,value),self.assertRaises(ValueError):self.preserve(one,two)
        self.assertFalse(target.exists())
    def test_wrong_owner_head_binding_and_changed_source_refuse(self):
        one,two=self.chain();q=copy.deepcopy(two['request']);q['pose_source_path']=str(one['run']/'pose_source.json')
        with self.assertRaises(ValueError),patch.object(result_bundle,'get',return_value=dict(watch=watch(one))):p.preserve(current(one),q,self.work,lambda *_:None)
        head=two['run']/'pose_source.json';raw=head.read_bytes();doc=json.loads(raw);doc['source_request_sha256']='0'*64;head.write_bytes(json.dumps(doc).encode());q=copy.deepcopy(two['request']);q['pose_source_hash']=pbr_contract.sha(head.read_bytes())
        with self.assertRaisesRegex(ValueError,'verified previous'),patch.object(result_bundle,'get',return_value=dict(watch=watch(one))):p.preserve(current(one),q,self.work,lambda *_:None)
        head.write_bytes(raw);read=pbr_contract.read;target=one['run']/'request.json';calls=0
        def race(path,*args):
            nonlocal calls
            data=read(path,*args)
            if Path(path)==target:
                calls+=1
                if calls>=1:return data+b'CHANGED'
            return data
        with patch.object(pbr_contract,'read',side_effect=race),self.assertRaises(ValueError):self.preserve(one,two)
    def test_reparse_flag_refuses_before_copy(self):
        one,two=self.chain();original=Path.lstat
        def lstat(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if path.name=='provenance' and path.parent.name==two['run'].name:return SimpleNamespace(st_file_attributes=0x400)
            return value
        before={f:f.read_bytes() for f in two['run'].rglob('*') if f.is_file()}
        with patch.object(Path,'lstat',lstat),self.assertRaisesRegex(ValueError,'reparse'):self.preserve(one,two)
        self.assertTrue(all(f.read_bytes()==raw for f,raw in before.items()))

    def test_production_closure_and_bundle_watch_include_protocol_files(self):
        u=ui3_fixture.UI3();u.root=self.work;c,record,index=u.artifact();run=Path(c['result_path']).parent;raw=b'{"immutable":"protocol evidence"}';h=pbr_contract.sha(raw);path=run/'provenance'/(h+'.json');path.parent.mkdir();path.write_bytes(raw)
        row=dict(role='protocol_provenance',asset_id='',source_path=str(path),path=str(path),sha256=h,bytes=len(raw));closure=Path(c['local_review']['source_closure']['path']);index['files'].append(row);r=json.dumps(index).encode();closure.write_bytes(r);c['local_review']['source_closure']['sha256']=pbr_contract.sha(r)
        bundle=result_bundle.get(c,self.work);self.assertEqual(bundle['watch'][str(path)],(h,len(raw)));path.write_bytes(b'CORRUPTED')
        with self.assertRaises(ValueError):result_bundle.get(c,self.work)
        path.write_bytes(raw);q=copy.deepcopy(c['request']);q.update(job_id='b'*32,operation='bake',output_directory=str(self.work/'jobs/runs'/('b'*32)));new=Path(q['output_directory']);new.mkdir();out=new/'provenance'/(h+'.json');out.parent.mkdir();out.write_bytes(raw);row.update(path=str(out))
        sealed,_,idx=job_assets.seal([record],q,self.work,lambda *_:None,[row]);self.assertIn(row,idx['files']);self.assertFalse(sealed['review_v1']['export_hulls']);job_assets.verify(idx,self.work,True)
        out.write_bytes(b'CORRUPTED')
        with self.assertRaises(ValueError):job_assets.verify(idx,self.work,True)
    def test_server_failure_and_cancel_stop_before_worker_and_keep_current(self):
        b=s.Run(assets=[dict(asset_id='a'*32,scale=.25,weight=1.)],simulation={},bake={});run=self.work/'jobs/runs'/('b'*32);run.mkdir(parents=True);cp=self.work/'jobs/current.json';cp.write_bytes(b'LASTGOOD');prior=dict(local_review=dict(snapshot=b.model_dump()))
        class Jobs:
            current=prior;active=dict(job_id='b'*32,output_directory=str(run));promote=Mock();cancel=Mock()
            def prepare(self,*args,**kwargs):return run/'request.json'
        for mode in ('failure','cancel'):
            state=dict(status='queued',token='token',events=[])
            def preserve(*args):
                if mode=='failure':raise ValueError('TEST_ONLY missing provenance')
                state['status']='cancelling';return []
            bounded=AsyncMock(side_effect=AssertionError('worker must not start'))
            with patch.multiple(s,WORK=self.work,jobs=Jobs(),assets={'a'*32:dict(enabled=True,physics=str(self.work/'geometry.obj'),metadata=dict(material_ready=True))},lock=asyncio.Lock(),run_state=state),patch.object(p,'preserve',preserve),patch.object(s.stored_assets,'stage',side_effect=lambda a,*_:copy.deepcopy(a)),patch.object(s,'bounded',bounded),patch.object(job_assets,'seal',side_effect=AssertionError('closure must not start')):
                asyncio.run(s.execute(b,'token',rebake=True))
            self.assertEqual(bounded.await_count,0);self.assertEqual(Jobs.promote.call_count,0);self.assertEqual(cp.read_bytes(),b'LASTGOOD');self.assertTrue(state['last_good_preserved']);self.assertEqual(state['status'],'failed' if mode=='failure' else 'cancelled')

if __name__=='__main__':unittest.main(verbosity=2)
