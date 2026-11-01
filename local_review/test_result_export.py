"""Closed ZIP pure transport tests; no server/native/Blender execution."""
import asyncio,copy,hashlib,importlib.util,io,json,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import server as s,result_export as e,pbr_contract as pbr,result_bundle
import test_ui3 as fixtures

class ResultExport(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='result_zip_');self.work=Path(self.temp.name);result_bundle._cache=None
    def tearDown(self):self.temp.cleanup()
    def fixture(self,saved=False):
        u=fixtures.UI3();u.root=self.work;c,record,index=u.artifact();root=Path(c['result_path']).parent
        q=c['request'];q['operation']='bake' if saved else 'simulate_bake';physical=b'{"TEST_ONLY":"physical payload"}';(root/'physics_inputs.json').write_bytes(physical);q['physics_input_hash']=e.digest(physical);q['physics_inputs_path']=str(root/'physics_inputs.json')
        origin=b'{"TEST_ONLY":"immutable origin"}';h=e.digest(origin);(root/'origin_result.json').write_bytes(origin);c['result']['origin']=dict(record_path='origin_result.json',record_sha256=h)
        if saved:
            q['review_v1']['export_hulls']=False
            (root/'provenance').mkdir();(root/'provenance'/(h+'.json')).write_bytes(origin)
            prior_request=b'{"TEST_ONLY":"prior request raw"}';rh=e.digest(prior_request);(root/'provenance'/(rh+'.json')).write_bytes(prior_request)
            prior_result=b'{"operation":"simulate_bake","TEST_ONLY":"prior result"}';sh=e.digest(prior_result);(root/'provenance'/(sh+'.json')).write_bytes(prior_result)
            ps=dict(kind='new',source_input_sha256=q['physics_input_hash'],source_request_sha256=rh,source=dict(record_sha256=sh),origin=dict(record_sha256=h))
            psraw=json.dumps(ps).encode();(root/'pose_source.json').write_bytes(psraw);q.update(pose_source_path=str(root/'pose_source.json'),pose_source_hash=e.digest(psraw))
        (root/'request.json').write_bytes(json.dumps(q).encode());c['result'].update(operation=q['operation']);(root/'result.json').write_bytes(json.dumps(c['result']).encode())
        side=root/'review-v1.json';doc=json.loads(side.read_bytes());doc['result_sha256']=e.digest((root/'result.json').read_bytes());
        if saved:doc['artifacts'].pop('hulls')
        raw=json.dumps(doc).encode();side.write_bytes(raw);c['local_review']['review']['event']['review'].update(sha256=e.digest(raw),bytes=len(raw))
        pointer=self.work/'jobs/current.json';pointer.write_bytes(json.dumps(c).encode())
        paths={str(root/name):e.digest((root/name).read_bytes()) for name in ('result.json','request.json','physics_inputs.json','origin_result.json')}
        if saved:paths[str(root/'pose_source.json')]=q['pose_source_hash']
        # Provenance semantics are exercised by core's accepted suite; this test
        # isolates export transport with actual production bundle/closure validation.
        return c,root,paths
    def build(self,c,paths):
        with patch.object(e.compat,'source',return_value=({},SimpleNamespace(paths=paths))):return e.build(c,self.work)
    def test_full_entries_SHA_rawJSON_maps_geometry_and_aliases(self):
        c,root,paths=self.fixture();before={p:p.read_bytes() for p in self.work.rglob('*') if p.is_file()};raw=self.build(c,paths)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            manifest=json.loads(z.read('manifest.json'));self.assertFalse(manifest['import_restore_supported']);self.assertEqual(manifest['hull_status'],'direct');self.assertEqual(len(z.namelist()),len(set(n.casefold() for n in z.namelist())))
            self.assertEqual(set(z.namelist()),{row['archive_path'] for row in manifest['files']}|{'manifest.json'})
            for row in manifest['files']:
                data=z.read(row['archive_path']);self.assertEqual(e.digest(data),row['sha256']);self.assertEqual(len(data),row['bytes'])
                if row['original_locator']:self.assertEqual(data,Path(row['original_locator']).read_bytes())
            for name in ('request.json','result.json','review-v1.json','physics_inputs.json'):self.assertEqual(z.read('job/'+name),(root/name).read_bytes())
            for role in e.MAPS:self.assertEqual(z.read('job/'+role+'.png'),(root/(role+'.png')).read_bytes())
            closure=json.loads((root/'inputs/review-assets/closure.json').read_bytes())
            for row in closure['files']:
                self.assertEqual(z.read(manifest['locator_mapping'][row['source_path']]),Path(row['path']).read_bytes())
        self.assertTrue(all(p.read_bytes()==b for p,b in before.items()))
    def test_saved_hash_referenced_provenance_is_included_without_directory_scan(self):
        c,root,paths=self.fixture(saved=True);(root/'provenance/UNRELATED.json').write_bytes(b'DO_NOT_EXPORT');raw=self.build(c,paths)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertNotIn('job/provenance/UNRELATED.json',z.namelist());self.assertEqual(json.loads(z.read('manifest.json'))['hull_status'],'absent');self.assertIn(b'Hull status: absent',z.read('README.txt'));ps=json.loads((root/'pose_source.json').read_bytes())
            for h in (ps['source_request_sha256'],ps['source']['record_sha256'],ps['origin']['record_sha256']):self.assertEqual(z.read('job/provenance/'+h+'.json'),(root/'provenance'/(h+'.json')).read_bytes())
    def test_two_saved_hops_follow_bundle_and_paired_request_not_missing_result_field(self):
        c,root,paths=self.fixture(saved=True);prior=json.loads((root/'pose_source.json').read_bytes());older_raw=(root/'pose_source.json').read_bytes();older_hash=e.digest(older_raw)
        (root/'provenance'/(older_hash+'.json')).write_bytes(older_raw)
        # Actual native result schema carries operation, never pose_source_hash.
        result_raw=b'{"operation":"bake","TEST_ONLY":"first Saved native result"}';result_hash=e.digest(result_raw);(root/'provenance'/(result_hash+'.json')).write_bytes(result_raw)
        request_raw=json.dumps(dict(operation='bake',pose_source_hash=older_hash)).encode();request_hash=e.digest(request_raw);(root/'provenance'/(request_hash+'.json')).write_bytes(request_raw)
        prior.update(source=dict(record_sha256=result_hash),source_request_sha256=request_hash,source_pose_source_sha256=older_hash)
        raw=json.dumps(prior).encode();(root/'pose_source.json').write_bytes(raw);c['request']['pose_source_hash']=e.digest(raw);(root/'request.json').write_bytes(json.dumps(c['request']).encode());(self.work/'jobs/current.json').write_bytes(json.dumps(c).encode())
        paths[str(root/'pose_source.json')]=e.digest(raw);paths[str(root/'request.json')]=e.digest((root/'request.json').read_bytes())
        result_bundle._cache=None;zip_raw=self.build(c,paths)
        with zipfile.ZipFile(io.BytesIO(zip_raw)) as z:
            self.assertEqual(z.read('job/provenance/'+older_hash+'.json'),older_raw);self.assertEqual(z.read('job/provenance/'+result_hash+'.json'),result_raw);self.assertEqual(z.read('job/provenance/'+request_hash+'.json'),request_raw);self.assertNotIn('pose_source_hash',json.loads(result_raw))
        # Rehash a plausible wrong request: a self-consistent blob is still not
        # the source bundle's declared prior-bundle binding.
        wrong=json.dumps(dict(operation='bake',pose_source_hash='0'*64)).encode();h=e.digest(wrong);(root/'provenance'/(h+'.json')).write_bytes(wrong);prior['source_request_sha256']=h
        raw=json.dumps(prior).encode();(root/'pose_source.json').write_bytes(raw);c['request']['pose_source_hash']=e.digest(raw);(root/'request.json').write_bytes(json.dumps(c['request']).encode());(self.work/'jobs/current.json').write_bytes(json.dumps(c).encode());paths[str(root/'pose_source.json')]=e.digest(raw);paths[str(root/'request.json')]=e.digest((root/'request.json').read_bytes())
        result_bundle._cache=None
        with self.assertRaisesRegex(ValueError,'Saved source/request bundle binding'):self.build(c,paths)

    def test_real_Blobs_save_two_saved_hops_refuse_missing_transitive_without_old_job_scan(self):
        spec=importlib.util.spec_from_file_location('zip_saved_protocol',Path(__file__).resolve().parent.parent/'tests/test_periodic_contract.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        jobs=self.work/'jobs';first=fixture.synthetic_current(jobs,version=2);one=fixture.saved(first,'2'*32)
        one['result'].pop('pose_source_hash',None);fixture.write(one['run']/'result.json',one['result'])
        two=fixture.saved(one,'3'*32);two['result'].pop('pose_source_hash',None);fixture.write(two['run']/'result.json',two['result'])
        c=dict(job_id='3'*32,request=two['request'],result=two['result'],result_path=str(two['run']/'result.json'))
        fixture.write(jobs/'current.json',c)
        proof,blobs=e.compat.source(jobs,c,two['wanted']);self.assertEqual(proof['poses'],two['result']['poses'])
        self.assertNotIn('pose_source_hash',two['result']);self.assertNotIn('pose_source_hash',one['result'])
        # Real Blobs.save, no TEST_ONLY transitive copy or missing-file repair.
        watch={str(two['run']/name):(e.digest((two['run']/name).read_bytes()),len((two['run']/name).read_bytes())) for name in ('request.json','result.json','physics_inputs.json')}
        bundle=dict(original={role:b'TEST_ONLY map dispatch marker' for role in e.MAPS},watch=watch,hulls=None)
        before={p:p.read_bytes() for p in jobs.rglob('*') if p.is_file()}
        with patch.object(result_bundle,'get',return_value=bundle),self.assertRaisesRegex(ValueError,'현재 job.*과거 출처 raw'):
            e.build(c,self.work)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))

    def test_member_traversal_duplicate_and_file_byte_limits(self):
        for name in ('../x','/root','x\\y','C:x','x/../y','x//y','x/.','x/hidden.','x\x00'):
            with self.subTest(name=name),self.assertRaises(ValueError):e.member(name)
        archive=e.Archive();archive.add('x',b'one')
        with self.assertRaises(ValueError):archive.add('X',b'two')
        with patch.object(e,'MAX_FILES',1),self.assertRaises(ValueError):archive.add('y',b'two')
        with patch.object(e,'MAX_BYTES',4),self.assertRaises(ValueError):archive.add('y',b'two')
        with patch.object(e,'MAX_ZIP_BYTES',4),self.assertRaises(ValueError):archive.pack()
    def test_changed_read_and_postcompression_sources_are_rejected(self):
        c,root,paths=self.fixture();read=pbr.read;target=root/'basecolor.png';before=target.read_bytes();calls=0
        def changed(path,*args):
            nonlocal calls
            raw=read(path,*args)
            if Path(path)==target:
                calls+=1
                if calls==3:return raw+b'CHANGED'
            return raw
        with patch.object(pbr,'read',side_effect=changed),self.assertRaises(ValueError):self.build(c,paths)
        self.assertEqual(target.read_bytes(),before);result_bundle._cache=None
        pack=e.Archive.pack
        def mutate(archive):
            raw=pack(archive);target.write_bytes(before+b'CHANGED');return raw
        with patch.object(e.Archive,'pack',mutate),self.assertRaises(ValueError):self.build(c,paths)
    def test_pointer_request_and_outside_provenance_rejected(self):
        c,root,paths=self.fixture();pointer=self.work/'jobs/current.json';raw=pointer.read_bytes();doc=json.loads(raw);doc['job_id']='0'*32;pointer.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(ValueError):self.build(c,paths)
        pointer.write_bytes(raw);doc=json.loads(raw);doc['unknown_top_payload']='CHANGED';pointer.write_bytes(json.dumps(doc).encode())
        with self.assertRaises(ValueError):self.build(c,paths)
        pointer.write_bytes(raw);outside=self.work/'unowned.json';outside.write_bytes(b'{}');bad=dict(paths);bad[str(outside)]=e.digest(b'{}')
        with self.assertRaises(ValueError):self.build(c,bad)
    def test_route_current_identity_and_download_headers(self):
        c,_,paths=self.fixture()
        async def exercise():
            with patch.multiple(s,WORK=self.work,jobs=SimpleNamespace(current=c),lock=asyncio.Lock()),patch.object(s,'is_busy',return_value=False),patch.object(e.compat,'source',return_value=({},SimpleNamespace(paths=paths))):
                r=await s.export_result(c['job_id']);self.assertEqual(r.media_type,'application/zip');self.assertEqual(r.headers['x-archive-sha256'],e.digest(r.body));self.assertIn(c['job_id'],r.headers['content-disposition'])
                with self.assertRaises(s.HTTPException):await s.export_result('0'*32)
            with patch.object(s,'is_busy',return_value=True),self.assertRaises(s.HTTPException):await s.export_result(c['job_id'])
        asyncio.run(exercise())

if __name__=='__main__':unittest.main(verbosity=2)
