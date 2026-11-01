"""UI3A pure/ASGI and synthetic artifact transport. No worker/Blender/browser."""
import asyncio,copy,hashlib,importlib.util,io,json,struct,subprocess,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
import server as s,height_field,result_bundle,job_assets,pbr_contract as pbr

BASE=Path(__file__).resolve().parent
class UI3(unittest.TestCase):
    def setUp(self):self.root=BASE/'test-output'/uuid.uuid4().hex;self.root.mkdir(parents=True);result_bundle._cache=None
    def height(self,codes,w,h):
        raw=struct.pack('<'+'H'*len(codes),*codes);image=Image.frombytes('I;16',(w,h),raw);out=io.BytesIO();image.save(out,format='PNG');return out.getvalue(),raw
    def artifact(self):
        spec=importlib.util.spec_from_file_location('n2purefixture',BASE.parent/'tests/test_review_native_pbr.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);doc,physics,_=m.prepare(self.root/'source');aid=doc['assets'][0]['asset_id'];folder=self.root/'source';glb=folder/'scene.glb';glb.write_bytes(b'glTF_TEST_ONLY_HASH_TRANSPORT');meta=dict(material_ready=True,material_records=doc['assets'][0]['materials'],files={name:s.sha(folder/name) for name in ('physics.obj','corners.json','scene.glb')});record=dict(asset_id=aid,name='TEST_ONLY transport fixture',folder=str(folder),physics=str(physics[aid]),source_hashes={str(physics[aid]):s.sha(physics[aid]),**{t['path']:t['content_sha256'] for t in doc['textures']}},metadata=meta,material_manifest=str(folder/'material-manifest.json'))
        run=self.root/'jobs/runs'/('a'*32);run.mkdir(parents=True);request=dict(job_id=run.name,output_directory=str(run),assets=[dict(asset_id=aid,path=str(physics[aid]),content_hash=s.sha(physics[aid]),format='obj',weight=1.,scale=1.,source_name='physics.obj')],simulation=dict(width=2.,depth=3.,edges='walls'),bake=dict(resolution=16,height_min=0.,height_max=8.,normal='DirectX'));reserve=[];request,closure,index=job_assets.seal([record],request,self.root,reserve.append);self.assertEqual(len(reserve),1);self.assertGreater(reserve[0],index['total_bytes'])
        cache=run.parent.parent/'assets'/(request['assets'][0]['content_hash']+'.obj');cache.parent.mkdir(exist_ok=True);cache.write_bytes(Path(request['assets'][0]['path']).read_bytes())
        result=dict(assets=copy.deepcopy(request['assets']),poses=[],execution=dict(physics_executed=False,body_count=0,steps=0),maps=dict(resolution=16,normal_convention='DirectX'));(run/'result.json').write_text(json.dumps(result),encoding='utf8');artifacts={};files={};hashes={}
        for role,mode,value in (('height','I;16',0),('normal','RGB',(128,64,255)),('coverage','L',255),('basecolor','RGB',(128,64,192)),('roughness','L',64),('metallic','L',192),('normal_material','RGB',(128,64,255))):
            path=run/(role+'.png');Image.new(mode,(16,16),value).save(path);raw=path.read_bytes()
            if role in ('height','normal','coverage'):files[role]=str(path);hashes[role]=pbr.sha(raw)
            else:
                d=dict(path=path.name,byte_sha256=pbr.sha(raw),byte_count=len(raw),format='PNG',width=16,height=16,bit_depth=8,color_type='RGB' if mode=='RGB' else 'GREY',color_space='sRGB' if role=='basecolor' else 'linear')
                if role=='normal_material':d['normal_convention']='DirectX'
                artifacts[role]=d
        hull=run/'hulls-v1.json';hull.write_text(json.dumps(dict(schema_version=1,coordinate_system='RH_Z_UP',units='meters',hulls=[])),encoding='utf8');raw=hull.read_bytes();artifacts['hulls']=dict(path=hull.name,byte_sha256=pbr.sha(raw),byte_count=len(raw),format='JSON',schema_version=1,hull_count=0,aggregate_vertex_count=0,aggregate_face_count=0,hulls=[])
        fp,binary=result_bundle.PRODUCERS['0.4.0-review.2'];doc=dict(version=1,job_id=run.name,result_sha256=s.sha(run/'result.json'),manifest_sha256=request['review_v1']['manifest_sha256'],producer=dict(implementation_version='0.4.0-review.2',build_fingerprint=fp,binary_sha256=binary),artifacts=artifacts);side=run/'review-v1.json';side.write_text(json.dumps(doc),encoding='utf8');raw=side.read_bytes();event=dict(event='completed',schema_version=2,job_id=run.name,result_path=str(run/'result.json'),review=dict(version=1,path=side.name,sha256=pbr.sha(raw),bytes=len(raw)));candidate=dict(job_id=run.name,result_path=str(run/'result.json'),request=request,result=result,files=files,hashes=hashes,local_review=dict(source_closure=closure,asset_renders=index['renders'],review=dict(event=event,build_fingerprint=fp,binary_sha256=binary)))
        return candidate,record,index
    def test_exact_height16_LE_codes_and_corruption_rejection(self):
        codes=[0,1,255,256,32768,65535];png,le=self.height(codes,3,2);meta,decoded=height_field.decode(png);self.assertEqual(decoded,le);self.assertEqual(list(struct.unpack('<6H',decoded)),codes);self.assertEqual(meta['decoded_sha256'],hashlib.sha256(le).hexdigest());self.assertEqual(meta['source_png_sha256'],hashlib.sha256(png).hexdigest())
        bad=bytearray(png);bad[-1]^=1
        with self.assertRaises(ValueError):height_field.decode(bytes(bad))
        out=io.BytesIO();Image.new('L',(3,2)).save(out,format='PNG')
        with self.assertRaises(ValueError):height_field.decode(out.getvalue())
    def test_job_closure_copies_originals_and_does_not_depend_on_import_afterward(self):
        c,record,index=self.artifact();before={p:pbr.sha(Path(p).read_bytes()) for p in record['source_hashes']};bundle=result_bundle.get(c,self.root);self.assertEqual(set(bundle['descriptors']),{'height','normal','coverage','basecolor','roughness','metallic','normal_material'});job_assets.verify(index,self.root,True)
        for p,h in before.items():self.assertEqual(pbr.sha(Path(p).read_bytes()),h)
        Path(record['folder'],'scene.glb').unlink();result_bundle._cache=None;self.assertIn('basecolor',result_bundle.get(c,self.root)['original']);self.assertTrue(Path(index['renders'][record['asset_id']]['glb_path']).is_file())
    def test_exact_sha_cache_and_map_tamper_rejection(self):
        c,_,_=self.artifact();first=result_bundle.get(c,self.root)
        with patch.object(pbr,'validate_artifacts',side_effect=AssertionError('Full parse should be cached')):self.assertIs(result_bundle.get(c,self.root),first)
        path=Path(c['result_path']).parent/'basecolor.png';raw=path.read_bytes();path.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        with self.assertRaisesRegex(ValueError,'bytes changed'):result_bundle.get(c,self.root)
    def test_reread_PBR_bytes_must_match_sealed_descriptor_before_cache(self):
        c,_,_=self.artifact();target=Path(c['result_path']).parent/'basecolor.png';out=io.BytesIO();Image.new('RGB',(16,16),(4,5,6)).save(out,format='PNG');replacement=out.getvalue();read=pbr.read;calls=0
        def changed(path,*args):
            nonlocal calls
            raw=read(path,*args)
            if Path(path)==target:
                calls+=1
                if calls>=2:return replacement
            return raw
        with patch.object(pbr,'read',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'Sealed bundle byte identity'):result_bundle.get(c,self.root)
        self.assertEqual(calls,2);self.assertIsNone(result_bundle._cache)
        restored=result_bundle.get(c,self.root);self.assertEqual(pbr.sha(restored['original']['basecolor']),restored['descriptors']['basecolor']['byte_sha256'])
    def test_result_sidecar_manifest_hull_and_HNC_reread_races_do_not_seed_watch(self):
        c,_,_=self.artifact();root=Path(c['result_path']).parent
        # Semantic-equivalent JSON with different bytes still violates its raw SHA.
        for target,occurrence in ((root/'result.json',2),(root/'review-v1.json',1),(Path(c['request']['review_v1']['manifest_path']),2),(root/'hulls-v1.json',2),(root/'normal.png',2)):
            with self.subTest(path=target.name):
                result_bundle._cache=None;read=pbr.read;calls=0
                def changed(path,*args):
                    nonlocal calls
                    raw=read(path,*args)
                    if Path(path)==target:
                        calls+=1
                        if calls>=occurrence:return raw+b' '
                    return raw
                with patch.object(pbr,'read',side_effect=changed):
                    with self.assertRaises(ValueError):result_bundle.get(c,self.root)
                self.assertGreaterEqual(calls,occurrence);self.assertIsNone(result_bundle._cache)
    def test_input_watch_publication_rejects_change_without_adopting_new_SHA(self):
        c,_,index=self.artifact();target=Path(next(item['path'] for item in index['files'] if item['role']=='corners'));read=pbr.read;calls=0
        def changed(path,*args):
            nonlocal calls
            raw=read(path,*args)
            if Path(path)==target:
                calls+=1
                if calls>=2:return raw+b' '
            return raw
        with patch.object(pbr,'read',side_effect=changed):
            with self.assertRaises(ValueError):result_bundle.get(c,self.root)
        self.assertEqual(calls,2);self.assertIsNone(result_bundle._cache)
    def test_core_owned_cache_readback_and_pre_promotion_share_sealed_bundle(self):
        c,_,_=self.artifact();before=copy.deepcopy(c);first=result_bundle.get(c,self.root);readback=copy.deepcopy(c);row=readback['request']['assets'][0];row['path']=str(Path(c['result_path']).parent.parent.parent/'assets'/(row['content_hash']+'.obj'));readback['result']['assets']=copy.deepcopy(readback['request']['assets']);current=result_bundle.get(readback,self.root)
        self.assertEqual(first['original'],current['original']);self.assertEqual(first['descriptors'],current['descriptors']);self.assertEqual(first['hulls'],current['hulls']);self.assertEqual(c,before)
        cache=Path(row['path']);saved=cache.read_bytes();cache.write_bytes(saved+b' ');result_bundle._cache=None
        with self.assertRaisesRegex(ValueError,'Sealed bundle byte identity'):result_bundle.get(c,self.root)
        self.assertIsNone(result_bundle._cache)
    def test_cache_alias_rejects_wrong_path_changed_payload_and_duplicate_asset(self):
        c,_,_=self.artifact();root=Path(c['result_path']).parent;readback=copy.deepcopy(c);row=readback['request']['assets'][0];row['path']=str(root.parent.parent/'assets'/(row['content_hash']+'.obj'));readback['result']['assets']=copy.deepcopy(readback['request']['assets'])
        invalid=[]
        for key,value in (('path',str(root/'arbitrary.obj')),('content_hash','0'*64),('asset_id','1'*32),('unknown_authored_field',1),('weight',True)):
            bad=copy.deepcopy(readback);bad['request']['assets'][0][key]=value;bad['result']['assets']=copy.deepcopy(bad['request']['assets']);invalid.append(bad)
        bad=copy.deepcopy(readback);bad['result']['execution']['steps']=1;invalid.append(bad)
        bad=copy.deepcopy(readback);bad['result']['assets'].append(copy.deepcopy(bad['result']['assets'][0]));invalid.append(bad)
        for bad in invalid:
            with self.subTest(result=bad['result']):
                result_bundle._cache=None
                with self.assertRaises(ValueError):result_bundle.get(bad,self.root)
                self.assertIsNone(result_bundle._cache)
    def test_ASGI_descriptors_height_and_raw_pixel_with_explicit_DX_preview(self):
        c,_,_=self.artifact();codes=[0,1,255,256,32768,65535]+[0]*250;encoded,expected_le=self.height(codes,16,16);height=Path(c['files']['height']);height.write_bytes(encoded);c['hashes']['height']=pbr.sha(encoded);jobs=type('Jobs',(),{'current':c})()
        with patch.object(s,'WORK',self.root),patch.object(s,'jobs',jobs),TestClient(s.app,base_url=s.ORIGIN,client=('127.0.0.1',45000)) as client:
            state=client.get('/api/state').json();current=state['current'];self.assertEqual(len(current['map_descriptors']),7);job=c['job_id'];meta=client.get(f'/api/height/{job}').json();binary=client.get(f'/api/height/{job}/data').content;self.assertEqual(binary,expected_le);self.assertEqual(list(struct.unpack_from('<6H',binary)),codes[:6]);self.assertEqual(pbr.sha(binary),meta['decoded_sha256']);pixel=client.get(f'/api/pixel/{job}/normal_material?x=0&y=0').json();self.assertEqual(pixel['values'],[128,64,255]);original=client.get(f'/api/maps/{job}/normal_material').content;preview=client.get(f'/api/maps/{job}/normal_material?preview=opengl').content;self.assertEqual(pbr.png(preview)['pixels'][:3],bytes([128,191,255]));self.assertEqual(s.sha(Path(c['result_path']).parent/'normal_material.png'),pbr.sha(original));self.assertEqual(client.get('/api/maps/'+'b'*32+'/height').status_code,404)
    def test_legacy_HNC_read_remains_explicitly_non_PBR(self):
        c,_,_=self.artifact();c['local_review']=None;result_bundle._cache=None;b=result_bundle.get(c,self.root);self.assertEqual(set(b['descriptors']),{'height','normal','coverage'});self.assertIsNone(b['doc']);self.assertIsNone(b['hulls'])
    def test_incomplete_material_is_geometry_only_and_quota_fails_before_copy(self):
        c,record,_=self.artifact();request=copy.deepcopy(c['request']);request.update(job_id='b'*32,output_directory=str(self.root/'jobs/runs'/('b'*32)));Path(request['output_directory']).mkdir();record['metadata']['material_ready']=False;sealed,_,index=job_assets.seal([record],request,self.root,lambda n:None);self.assertFalse(sealed['review_v1']['bake_pbr']);self.assertFalse(index['pbr']);self.assertTrue(index['pbr_unavailable'])
        request.update(job_id='c'*32,output_directory=str(self.root/'jobs/runs'/('c'*32)));Path(request['output_directory']).mkdir()
        def quota(n):raise ValueError('quota sentinel')
        with self.assertRaisesRegex(ValueError,'quota sentinel'):job_assets.seal([record],request,self.root,quota)
        self.assertFalse(Path(request['output_directory'],'inputs/review-assets').exists())
    def test_owned_worker_error_message_is_preserved(self):
        class Pipe:
            def __init__(self,data):self.data=data
            async def read(self,n):value=self.data;self.data=b'';return value
        class Proc:
            returncode=1
            def __init__(self):self.stdout=Pipe(b'{"event":"error","message":"PBR input budget exceeds512MiB"}\n');self.stderr=Pipe(b'')
            async def wait(self):return 1
        async def spawn(*args,**kwargs):return Proc()
        async def exercise():
            with patch.object(s,'WORK',self.root),patch.object(asyncio,'create_subprocess_exec',spawn):
                with self.assertRaisesRegex(ValueError,'PBR input budget exceeds512MiB'):await s.bounded(['TEST_ONLY','request.json'],self.root/'error-logs',1,events=True)
        asyncio.run(exercise())
    def test_surface_LE_row_direction_LOD_and_no_height_canvas(self):
        script=r"""
import assert from 'node:assert/strict';import * as THREE from 'three';import {decodeHeight,heightGeometry} from './web/surface.js';
const values=[0,1,255,256,32768,65535],buffer=new ArrayBuffer(12),view=new DataView(buffer);values.forEach((v,i)=>view.setUint16(i*2,v,true));const meta={width:3,height:2,byte_length:12,dtype:'uint16',byte_order:'little',height_min:0,height_max:8,region_width:2,region_depth:4};const codes=decodeHeight(buffer,meta);assert.deepEqual([...codes],values);const g=heightGeometry(meta,codes,513),p=g.attributes.position;assert.equal(p.getY(0),2);assert.equal(p.getY(3),-2);assert.equal(p.getZ(0),0);assert.equal(p.getZ(5),8);assert.ok(p.getZ(1)>0&&p.getZ(1)<.001);assert.equal(g.index.count,12);assert.equal(g.userData.lod.cols,3);assert.equal(g.userData.lod.rows,2);assert.throws(()=>decodeHeight(buffer,{...meta,byte_order:'big'}));const large={...meta,width:2048,height:2048,byte_length:2048*2048*2};const big=new Uint16Array(2048*2048);const lod=heightGeometry(large,big,513);assert.equal(lod.attributes.position.count,513*513);const material=new THREE.MeshStandardMaterial({normalMapType:THREE.ObjectSpaceNormalMap});assert.equal(material.normalMapType,THREE.ObjectSpaceNormalMap);g.dispose();lod.dispose();material.dispose();console.log('PASS');
"""
        result=subprocess.run(['node','--input-type=module','-'],input=script,text=True,capture_output=True,cwd=BASE,timeout=30);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        source=(BASE/'web/surface.js').read_text(encoding='utf8');self.assertNotIn('getImageData',source);self.assertIn('getUint16(i*2,true)',source);self.assertIn('ObjectSpaceNormalMap',source);self.assertNotIn('normalScale',source)

if __name__=='__main__':unittest.main()
