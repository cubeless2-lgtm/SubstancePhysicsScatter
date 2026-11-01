"""Stored asset recovery and actual-Hull host proof: pure sealed fixtures only."""
import copy,json,tempfile,unittest,uuid,sys,subprocess
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'plugin'))
import result_bundle,stored_assets,stored_hulls,pbr_contract as pbr,material_revision as m,job_assets
import test_ui3 as fixtures
import test_material_revision as glb_fixture

class StoredReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='stored_review_');self.work=Path(self.temp.name);result_bundle._cache=None
        # These minimal artifact fixtures are not physics protocol records. The
        # accepted core source validator is reused in production, while this
        # test isolates copied raw binding + actual N2 bundle validation.
        self.protocol_patch=patch.object(stored_hulls.compat,'source',side_effect=self.protocol);self.protocol_patch.start()
    def tearDown(self):self.protocol_patch.stop();self.temp.cleanup()
    def protocol(self,base,origin,physical):
        run=Path(origin['result_path']).parent;paths={};data={}
        for name in ('request.json','result.json','physics_inputs.json','origin_result.json'):
            raw=(run/name).read_bytes();h=pbr.sha(raw);paths[str(run/name)]=h;data[h]=raw
        return dict(source_request_sha256=paths[str(run/'request.json')],source=dict(record_sha256=paths[str(run/'result.json')])),SimpleNamespace(paths=paths,data=data)

    def artifact(self,folder=None):
        u=fixtures.UI3();u.root=folder or self.work;c,record,index=u.artifact();aid=record['asset_id'];run=Path(c['result_path']).parent
        record['metadata']['schema_version']=2;records=record['metadata']['material_records'];doc=dict(asset=dict(version='2.0'),buffers=[dict(byteLength=36)],materials=[dict(name='ReviewMat_'+str(row['material_id']),pbrMetallicRoughness=dict(baseColorFactor=[*row['base_color_factor'],1.],roughnessFactor=row['roughness_factor'],metallicFactor=row['metallic_factor'])) for row in records],meshes=[dict(primitives=[dict(material=0,attributes=dict(POSITION=0,NORMAL=1,TANGENT=2,TEXCOORD_0=3))])])
        raw=glb_fixture.glb(doc);source=Path(record['folder'])/'scene.glb';source.write_bytes(raw);record['metadata']['files']['scene.glb']=pbr.sha(raw);record.update(enabled=True,scale=1.,weight=1.,source=record['physics'],render_revision=pbr.sha(raw),material_revision=m.identity(records))
        native=pbr.rawjson(Path(record['material_manifest']).read_bytes());record['texture_options']=[dict(texture_id=t['texture_id'],source_sha256=t['content_sha256'],source_name=Path(t['path']).name) for t in native['textures']]
        for row in index['files']:
            if row['role']=='render':Path(row['path']).write_bytes(raw);row.update(sha256=pbr.sha(raw),bytes=len(raw))
        pin=c['local_review']['asset_renders'][aid];pin.update(glb_sha256=pbr.sha(raw),render_revision=pbr.sha(raw),material_revision=record['material_revision']);index['renders'][aid]=copy.deepcopy(pin)
        closure=Path(c['local_review']['source_closure']['path']);data=json.dumps(index).encode();closure.write_bytes(data);c['local_review']['source_closure']['sha256']=pbr.sha(data)
        c['result']['poses']=[dict(id=0,asset_id=aid,position=[0.,0.,0.],rotation=[0.,0.,0.,1.],scale=c['request']['assets'][0]['scale'])]
        hull=dict(asset_id=aid,physics_obj_sha256=c['request']['assets'][0]['content_hash'],built_scale=c['request']['assets'][0]['scale'],coordinate_space='scaled_asset_origin_local',center_of_mass_scaled=[0.,0.,0.],convex_radius=0.,vertices=[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.],[0.,0.,1.]],faces=[[0,2,1],[0,1,3],[0,3,2],[1,2,3]],Jolt_version='5.2.0',shape_type='ConvexHull',max_hull_points=256,construction_tolerance=0.)
        hraw=json.dumps(dict(schema_version=1,coordinate_system='RH_Z_UP',units='meters',hulls=[hull])).encode();(run/'hulls-v1.json').write_bytes(hraw);side=run/'review-v1.json';side_doc=json.loads(side.read_bytes());side_doc['artifacts']['hulls'].update(byte_sha256=pbr.sha(hraw),byte_count=len(hraw),hull_count=1,aggregate_vertex_count=4,aggregate_face_count=4,hulls=[dict(asset_id=aid,vertex_count=4,face_count=4)]);side.write_bytes(json.dumps(side_doc).encode())
        physical=b'{"TEST_ONLY":"physics input"}';(run/'physics_inputs.json').write_bytes(physical);c['request']['physics_input_hash']=pbr.sha(physical);c['result']['pose_origin']=dict(job_id=c['job_id'],record_sha256=pbr.sha(b'RAW ORIGIN'));(run/'origin_result.json').write_bytes(b'RAW ORIGIN');c['request']['operation']='simulate_bake';self.reseal(c)
        return c,record,index
    def reseal(self,c):
        root=Path(c['result_path']).parent;(root/'request.json').write_bytes(json.dumps(c['request']).encode());(root/'result.json').write_bytes(json.dumps(c['result']).encode());side=root/'review-v1.json';doc=json.loads(side.read_bytes());doc['result_sha256']=pbr.sha((root/'result.json').read_bytes());raw=json.dumps(doc).encode();side.write_bytes(raw);c['local_review']['review']['event']['review'].update(sha256=pbr.sha(raw),bytes=len(raw));result_bundle._cache=None
    def test_readonly_missing_source_recovery_stage_factor_and_revision_rejection(self):
        c,a,index=self.artifact();scene=Path(a['folder'],'scene.glb').read_bytes();Path(a['folder']).rename(self.work/'MOVED_IMPORT_COPY');before={p:p.read_bytes() for p in self.work.rglob('*') if p.is_file()};raw,label=stored_assets.scene_raw(a,c,self.work);self.assertEqual(raw,scene);self.assertIn('job-owned',label)
        tid=a['metadata']['material_records'][0]['base_color_texture']['texture_id'];raw,label=stored_assets.texture_raw(a,c,self.work,tid);self.assertEqual(pbr.sha(raw),tid);self.assertEqual(set(before),{p for p in self.work.rglob('*') if p.is_file()})
        recovered=stored_assets.stage(a,c,self.work,self.work/'derived/stage');self.assertEqual(recovered['metadata'],a['metadata']);self.assertTrue(Path(recovered['physics']).is_file());self.assertEqual(pbr.sha(Path(recovered['physics']).read_bytes()),a['metadata']['files']['physics.obj'])
        # A subsequent Saved copies the recovered originals again. The original
        # catalog remains unchanged and still resolves through explicit aliases.
        q=copy.deepcopy(c['request']);q.update(job_id='d'*32,operation='bake',output_directory=str(self.work/'jobs/runs'/('d'*32)));Path(q['output_directory']).mkdir();q,closure,index2=job_assets.seal([recovered],q,self.work,lambda *_:None);job_assets.verify(index2,self.work,True);self.assertTrue(index2['source_aliases'])
        next_view=copy.deepcopy(c);next_view.update(job_id='d'*32,result_path=str(Path(q['output_directory'])/'result.json'),request=q);next_view['local_review'].update(source_closure=closure,asset_renders=index2['renders'])
        with patch.object(result_bundle,'get',return_value=dict()):
            again,label=stored_assets.scene_raw(a,next_view,self.work);self.assertEqual(again,scene);self.assertIn('job-owned',label)
        updated,_=m.build_revision(recovered,self.work,self.work/'new-material',{'0':{'roughness_factor':.375}});self.assertEqual(updated['asset_id'],a['asset_id']);self.assertEqual(updated['metadata']['files']['physics.obj'],a['metadata']['files']['physics.obj']);self.assertEqual(updated['metadata']['material_records'][0]['roughness_factor'],.375)
        changed=copy.deepcopy(a);changed['material_revision']='0'*64
        with self.assertRaisesRegex(ValueError,'revision'):stored_assets.scene_raw(changed,c,self.work)
        self.assertTrue(all(p.read_bytes()==raw for p,raw in before.items()))
    def test_missing_original_requires_exact_closed_mapping(self):
        c,a,index=self.artifact();key=next(iter(a['source_hashes']));data=Path(key).read_bytes();Path(key).unlink();raw,label=stored_assets.source_raw(a,c,self.work,key,a['source_hashes'][key]);self.assertEqual(raw,data);self.assertIn('job-owned',label)
        bad=copy.deepcopy(a);bad['source_hashes'][key]='0'*64
        with self.assertRaises(ValueError):stored_assets.source_raw(bad,c,self.work,key,'0'*64)
    def child(self,c,identity):
        root=Path(c['result_path']).parent;run=root.parent/identity;run.mkdir();# synthetic copy of sealed fixtures, not native/Jolt output
        import shutil
        for name in ('height.png','normal.png','coverage.png','basecolor.png','roughness.png','metallic.png','normal_material.png'):shutil.copyfile(root/name,run/name)
        q=copy.deepcopy(c['request']);q.update(job_id=identity,operation='bake',output_directory=str(run));q['review_v1']['export_hulls']=False
        result=copy.deepcopy(c['result']);result['execution']=dict(physics_executed=False,body_count=0,steps=0)
        child=copy.deepcopy(c);child.update(job_id=identity,result_path=str(run/'result.json'),request=q,result=result,files={role:str(run/(role+'.png')) for role in ('height','normal','coverage')});child['local_review'].pop('inherited_hull',None);child['local_review'].pop('source_closure',None);child['local_review']['asset_renders']={}
        side=json.loads((root/'review-v1.json').read_bytes());side.update(job_id=identity);side['artifacts'].pop('hulls',None);(run/'review-v1.json').write_bytes(json.dumps(side).encode());event=child['local_review']['review']['event'];event.update(job_id=identity,result_path=str(run/'result.json'));self.reseal(child)
        return child
    def test_direct_to_Saved_to_Saved_inherited_exact_and_restart(self):
        origin,a,index=self.artifact();child=self.child(origin,'b'*32);ref,reason=stored_hulls.preserve(origin,child,self.work,lambda *_:None);self.assertIsNone(reason);child['local_review']['inherited_hull']=ref;result_bundle._cache=None
        value=result_bundle.get(child,self.work);self.assertEqual(value['hull_status'],'inherited');self.assertEqual(value['hulls'],result_bundle.get(origin,self.work)['hulls'])
        next_child=self.child(child,'c'*32);ref,_=stored_hulls.preserve(child,next_child,self.work,lambda *_:None);next_child['local_review']['inherited_hull']=ref;plain=json.loads(json.dumps(next_child));result_bundle._cache=None;value=result_bundle.get(plain,self.work);self.assertEqual(value['hull_status'],'inherited');self.assertEqual(value['inherited']['origin_job_id'],origin['job_id']);self.assertTrue(any('inherited-hull' in p for p in value['watch']))
    def test_bad_origin_or_pose_is_absent_not_synthetic_and_maps_survive(self):
        origin,a,index=self.artifact();child=self.child(origin,'b'*32);ref,_=stored_hulls.preserve(origin,child,self.work,lambda *_:None);child['local_review']['inherited_hull']=ref
        Path(origin['result_path']).write_bytes(b'BROKEN_ORIGIN');result_bundle._cache=None;value=result_bundle.get(child,self.work);self.assertEqual(value['hull_status'],'absent');self.assertIsNone(value['hulls']);self.assertEqual(len(value['descriptors']),7);self.assertIn('검증 Hull 없음',value['hull_reason'])
        bad=copy.deepcopy(child);bad['result']['pose_origin']={}
        with self.assertRaises(ValueError):stored_hulls.same_geometry(origin,bad)
        bad=copy.deepcopy(child);bad['request']['assets'][0]['scale']=2.
        with self.assertRaises(ValueError):stored_hulls.same_geometry(origin,bad)
    def test_old_Saved_without_a_trusted_ref_stays_absent(self):
        origin,a,index=self.artifact();child=self.child(origin,'b'*32);result_bundle._cache=None;bundle=result_bundle.get(child,self.work);self.assertEqual(bundle['hull_status'],'absent');self.assertIsNone(bundle['hulls'])

    def test_same_job_hull_absent_clears_actual_UI_state_hook(self):
        script=r"""import {syncHullState} from './web/ui2.js';import assert from 'node:assert/strict';import fs from 'node:fs';
const old={job_id:'same',hull_status:'inherited',review:{status:'inherited',url:'/api/hulls/same'}};const absent={job_id:'same',hull_status:'absent',review:null,hull_reason:'origin missing'};let disposed=0,lastHull={};const checkbox={checked:true};assert.equal(syncHullState(absent,old,checkbox,()=>{disposed++;lastHull=null;}),true);assert.equal(disposed,1);assert.equal(lastHull,null);assert.equal(checkbox.checked,false);assert.equal(syncHullState(absent,absent,checkbox,()=>disposed++),false);assert.equal(syncHullState({...absent,job_id:'other'},old,checkbox,()=>disposed++),false);assert.equal(disposed,1);const app=fs.readFileSync('web/app.js','utf8');assert.ok(app.includes('||hullChanged)'));assert.ok(app.includes('disposeHulls(lastHull);lastHull=null;'));
"""
        r=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf8',capture_output=True,cwd=Path(__file__).resolve().parent,timeout=15);self.assertEqual(r.returncode,0,r.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
