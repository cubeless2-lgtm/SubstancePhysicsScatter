"""Saved rebake handlers/protocol/closure, no HTTP/native/Blender execution."""
import asyncio,copy,hashlib,importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
import server as s,job_assets,result_bundle
import test_ui3 as ui3_fixture
BASE=Path(__file__).resolve().parent
AID='a'*32

def body(mask=None):return s.Run(assets=[dict(asset_id=AID,scale=.25,weight=2.)],simulation=dict(count=20,width=2.,depth=2.,seconds=2.,seed=123456789,edges='walls'),bake=dict(resolution=64,height_min=0.,height_max=8.,normal='OpenGL',samples=1),mask_id=mask)

class SavedRebake(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='saved_rebake_');self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_mask_selection_and_missing_source_are_explicitly_rejected(self):
        b=body();prior=dict(local_review=dict(snapshot=b.model_dump()))
        for current,changed in ((None,b),(dict(local_review={}),b),(prior,body('b'*32))):
            with patch.object(s,'jobs',SimpleNamespace(current=current)),self.assertRaises(ValueError):s.saved_source(changed)
        with patch.object(s,'jobs',SimpleNamespace(current=prior)):self.assertIs(s.saved_source(b),prior)
    def exercise(self,failure=None,cancel=False):
        root=self.root;run=root/'jobs/runs'/('c'*32);run.mkdir(parents=True);current=root/'jobs/current.json';current.write_bytes(b'LAST_GOOD')
        b=body();poses=[dict(id=17,asset_id=AID)];origin=dict(record_sha256='d'*64)
        prior=dict(local_review=dict(snapshot=b.model_dump()),result=dict(poses=poses,pose_origin=origin))
        request=dict(job_id=run.name,operation='bake',output_directory=str(run),assets=[],physics_input_format_version=2)
        candidate=dict(result=dict(poses=copy.deepcopy(poses),pose_origin=copy.deepcopy(origin),execution=dict(physics_executed=False,body_count=0,steps=0)))
        if failure=='origin':candidate['result']['pose_origin']={}
        if failure=='physics':candidate['result']['execution']['steps']=1
        class Jobs:
            def __init__(self):self.current=prior;self.active=copy.deepcopy(request);self.promoted=0;self.cancelled=0;self.kw=None
            def prepare(self,*args,**kwargs):
                self.kw=kwargs
                if failure=='physical':raise ValueError('Simulation settings changed. Run Simulate first.')
                (run/'request.json').write_text(json.dumps(self.active));return run/'request.json'
            def validate(self,*args):return candidate
            def promote(self,c):self.promoted+=1
            def cancel(self):self.cancelled+=1
        jobs=Jobs();record=dict(asset_id=AID,enabled=True,physics=str(root/'physics.obj'),metadata=dict(material_ready=True,material_records=[dict(roughness_factor=.125)]));(root/'physics.obj').write_bytes(b'TEST_ONLY')
        fp,binary=result_bundle.LIVE_PRODUCERS['0.4.0-review.2'];fpfile=root/'fingerprint';fpfile.write_text(fp)
        def seal(records,req,*args):
            self.assertEqual(records[0]['metadata']['material_records'][0]['roughness_factor'],.125)
            req=copy.deepcopy(req);req['review_v1']=dict(export_hulls=False,bake_pbr=True)
            return req,{},dict(renders={AID:dict(material_revision='NEW_MATERIAL')},pbr_unavailable=[])
        calls=[]
        async def bounded(*args):
            calls.append(args)
            if failure=='worker':raise ValueError('TEST_ONLY worker failure')
            if cancel:s.run_state['status']='cancelling'
            return [dict(event='completed',job_id=run.name)]
        state=dict(status='queued',token='token',events=[])
        with patch.multiple(s,WORK=root,jobs=jobs,assets={AID:record},lock=asyncio.Lock(),run_state=state,PBR_FINGERPRINT=fpfile),patch.object(s,'space_budget'),patch.object(s,'sha',return_value=binary),patch.object(s,'bounded',bounded),patch.object(job_assets,'seal',seal),patch.object(job_assets,'verify'),patch.object(result_bundle,'get'),patch.object(s.saved_provenance,'preserve',return_value=[]),patch.object(s.stored_assets,'stage',side_effect=lambda a,*_:copy.deepcopy(a)),patch.object(s.stored_hulls,'preserve',return_value=(None,None)):
            asyncio.run(s.execute(b,'token',rebake=True))
        self.assertEqual(jobs.kw,dict(rebake=True,host_mode='saved_input'));self.assertEqual(current.read_bytes(),b'LAST_GOOD')
        self.assertEqual(jobs.promoted,0 if failure or cancel else 1)
        if failure or cancel:
            self.assertEqual(state['status'],'cancelled' if cancel else 'failed');self.assertTrue(state['last_good_preserved'])
        else:
            self.assertEqual(state['status'],'completed');self.assertEqual(candidate['local_review']['input_mode'],'saved_input');self.assertIsNone(candidate['local_review']['snapshot']['mask_id']);self.assertEqual(candidate['local_review']['asset_renders'][AID]['material_revision'],'NEW_MATERIAL')
        self.assertLessEqual(len(calls),1)
    def test_actual_execute_saved_flags_latest_revision_and_single_promote(self):self.exercise()
    def test_physical_change_stops_before_native(self):self.exercise(failure='physical')
    def test_worker_failure_preserves_lastgood(self):self.exercise(failure='worker')
    def test_cancel_preserves_lastgood(self):self.exercise(cancel=True)
    def test_pose_origin_and_physics_zero_gate_prevents_promote(self):
        for failure in ('origin','physics'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                self.root=Path(folder);self.exercise(failure=failure)
    def test_real_closure_bake_flags_and_absent_hull_bundle(self):
        fixture=ui3_fixture.UI3();fixture.root=self.root;c,record,index=fixture.artifact();result_bundle._cache=None
        # Same production sealing, with a new owned run and unchanged material inputs.
        req=copy.deepcopy(c['request']);req.update(operation='bake',job_id='b'*32,output_directory=str(self.root/'jobs/runs'/('b'*32)));Path(req['output_directory']).mkdir()
        sealed,_,_=job_assets.seal([record],req,self.root,lambda *_:None)
        self.assertEqual(sealed['review_v1']['export_hulls'],False);self.assertEqual(sealed['review_v1']['bake_pbr'],True)
        c['request']['review_v1']['export_hulls']=False;run=Path(c['result_path']).parent;side=run/'review-v1.json';doc=json.loads(side.read_bytes());doc['artifacts'].pop('hulls');raw=json.dumps(doc).encode();side.write_bytes(raw)
        event=c['local_review']['review']['event']['review'];event.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        bundle=result_bundle.get(c,self.root);self.assertIsNone(bundle['hulls']);self.assertEqual(len(bundle['descriptors']),7)
    def test_real_core_saved_physical_guard_and_origin_bytes_without_worker(self):
        spec=importlib.util.spec_from_file_location('saved_protocol_fixture',BASE.parent/'tests/protocol_fixture.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
        jobs=s.Jobs(self.root/'corejobs');rows=[dict(asset_id=AID,path=str(BASE.parent/'tests/fixtures/cube.obj'),scale=.25,weight=2.,format='obj')];b=body();path=jobs.prepare(rows,b.simulation.model_dump(),b.bake.model_dump());f.synthetic_current(jobs,path,[dict(id=i,asset_id=AID,position=[0.,0.,float(i)],rotation=[0.,0.,0.,1.],scale=.25) for i in range(20)])
        before=(jobs.directory/'current.json').read_bytes();old=jobs.current;new=jobs.prepare(rows,b.simulation.model_dump(),b.bake.model_dump(),rebake=True,host_mode='saved_input');req=json.loads(new.read_bytes());self.assertEqual(req['operation'],'bake');self.assertEqual(req['simulation_key'],old['request']['simulation_key']);self.assertEqual(json.loads(Path(req['pose_source_path']).read_bytes())['origin'],old['result']['pose_origin'])
        changed=b.simulation.model_dump();changed['width']=3.
        with self.assertRaises(ValueError):jobs.prepare(rows,changed,b.bake.model_dump(),rebake=True,host_mode='saved_input')
        self.assertEqual((jobs.directory/'current.json').read_bytes(),before)
    def test_explicit_load_saved_settings_restores_physical_fields_without_touching_revisions(self):
        script=r"""import fs from 'node:fs';import assert from 'node:assert/strict';
const app=fs.readFileSync('web/app.js','utf8');const drafts=new Map();const draft=eval('('+app.match(/function draft\(a\)\{[^\n]+/)[0]+')');
let busy=false,maskId='changed';const catalog=[{asset_id:'a',enabled:true,scale:1,weight:1,metadata:{units:'m',source_up_axis:'Z'},render_revision:'LATEST_MATERIAL'},{asset_id:'b',enabled:true,scale:1,weight:1,metadata:{units:'m',source_up_axis:'Z'},render_revision:'other'}];
const fields=['count','width','resolution'];const elements=Object.fromEntries([...fields,'maskInput','maskName'].map(k=>[k,{value:'draft'}]));const $=id=>elements[id];let calls=0;const library=()=>calls++,dirty=()=>{},display=()=>{};
const lastGood={settings:{snapshot:{assets:[{asset_id:'a',scale:2.75,weight:8}],simulation:{count:60,width:1},bake:{resolution:512},mask_id:'saved'}}};
const loadSavedSettings=eval('('+app.match(/function loadSavedSettings\(\)\{[^\n]+/)[0]+')');loadSavedSettings();assert.equal(elements.count.value,60);assert.equal(elements.width.value,1);assert.equal(elements.resolution.value,512);assert.equal(draft(catalog[0]).scale,2.75);assert.equal(draft(catalog[0]).weight,8);assert.equal(draft(catalog[1]).selected,false);assert.equal(maskId,'saved');assert.equal(catalog[0].render_revision,'LATEST_MATERIAL');assert.equal(calls,1);
elements.width.value=99;assert.equal(elements.width.value,99);catalog[0].enabled=false;assert.throws(loadSavedSettings,/누락/);assert.equal(elements.width.value,99);
"""
        r=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding="utf-8",capture_output=True,cwd=BASE,timeout=15);self.assertEqual(r.returncode,0,r.stderr)

    def test_actual_draft_preserves_selection_scale_weight_and_invalidates_only_material(self):
        script=r"""import fs from 'node:fs';import assert from 'node:assert/strict';
const app=fs.readFileSync('web/app.js','utf8');const match=app.match(/function draft\(a\)\{[^\n]+/);assert.ok(match);
const drafts=new Map();const draft=eval('('+match[0]+')');const a={asset_id:'a',scale:1,weight:1,metadata:{units:'m',source_up_axis:'Z'},render_revision:'old'};
const d=draft(a);Object.assign(d,{scale:2.75,weight:8,selected:false,material_factors:{old:1}});a.render_revision='new';assert.equal(draft(a),d);assert.equal(d.scale,2.75);assert.equal(d.weight,8);assert.equal(d.selected,false);assert.equal(d.material_factors,undefined);assert.ok(!app.includes('drafts.delete(a.asset_id)'));
assert.ok(app.includes("rebake?'/api/rebake':'/api/run'"));assert.ok(app.includes('body.mask_id!==lastGood?.settings?.snapshot?.mask_id'));
"""
        r=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding="utf-8",capture_output=True,cwd=BASE,timeout=15);self.assertEqual(r.returncode,0,r.stderr)
        text=(BASE/'web/ui2.js').read_text('utf8');self.assertIn('미확인 · 재가져오기 필요',text);self.assertIn('Array.isArray(asset.metadata.uv_layers)',text)

if __name__=='__main__':unittest.main(verbosity=2)
