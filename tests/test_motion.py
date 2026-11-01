"""Motion codec/owned closure tests; synthetic records are not Jolt evidence."""
from pathlib import Path
import ast,asyncio,copy,hashlib,json,struct,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'));sys.path.insert(0,str(ROOT/'local_review'))
from substance_physics_scatter import motion
from test_periodic_contract import synthetic_current,saved


def example(result=None,result_sha=None):
    if result is None:
        pose=dict(id=0,asset_id='a'*32,scale=.25,position=[0.,0.,.5],rotation=[0.,0.,0.,1.])
        result=dict(job_id='1'*32,operation='simulate_bake',status='completed',coordinate_system='RH_Z_UP',units='meters',physics_input_format_version=2,steps=12,poses=[pose],assets=[dict(asset_id='a'*32)],physics_input_hash='b'*64,pose_origin=dict(job_id='1'*32,record_sha256='c'*64))
    poses=result['poses'];periodic=result['physics_input_format_version']==3;hz=60 if periodic else 120;sub=16 if periodic else 1;stride=2 if periodic else 4
    steps=result['steps']//sub
    frame_steps=[0]+list(range(stride,steps+1,stride))
    if frame_steps[-1]!=steps:frame_steps.append(steps)
    frames=[dict(step=i,time=i/hz,positions=[p['position'][:] for p in poses],rotations=[p['rotation'][:] for p in poses]) for i in frame_steps]
    fp,exe=next(iter(motion.PRODUCERS.items()))
    data=dict(schema_version=1,coordinate_system='RH_Z_UP',units='meters',source_job_id=result['job_id'],result_sha256=result_sha or 'd'*64,physics_input_hash=result['physics_input_hash'],pose_origin=result['pose_origin'],producer=dict(implementation_version='0.4.0-motion.1',build_fingerprint=fp,binary_sha256=exe),bodies=[{k:p[k] for k in ('id','asset_id','scale')} for p in poses],sampling=dict(solver_hz=hz,substeps=sub,stride=stride,target_hz=30),frames=frames,final_poses_sha256=motion.pose_hash(poses))
    return data,result

def raw(data):return json.dumps(data,allow_nan=False,separators=(',',':')).encode()


class Motion(unittest.TestCase):
    def test_codec_final_pose_binary_signedzero_and_actual_sampling(self):
        data,result=example();meta=motion.validate(raw(data),result,'d'*64,'b'*64)
        self.assertEqual(meta['frame_count'],4);self.assertEqual(meta['duration_seconds'],.1)
        p=result['poses'][0];aid=p['asset_id'].encode()
        expected=b'motion-final-poses-v1\0'+struct.pack('<III',1,p['id'],len(aid))+aid+struct.pack('<8d',p['scale'],*p['position'],*p['rotation'])
        self.assertEqual(data['final_poses_sha256'],hashlib.sha256(expected).hexdigest())
        source=(ROOT/'worker/motion.h').read_text(encoding='utf8');self.assertIn('"motion-final-poses-v1\\0",22',source)
        bad=copy.deepcopy(data);bad['frames'][-1]['positions'][0][0]=-0.
        with self.assertRaisesRegex(ValueError,'pose bits'):motion.validate(raw(bad),result,'d'*64,'b'*64)
    def test_rejects_unknown_producer_identity_timestamps_types_and_bounds(self):
        data,result=example()
        variants={
            'unknown':lambda x:x.update(unknown=1),
            'producer':lambda x:x['producer'].update(binary_sha256='0'*64),
            'source':lambda x:x.update(source_job_id='2'*32),
            'origin':lambda x:x['pose_origin'].update(record_sha256='e'*64),
            'cpu_time':lambda x:x['frames'][1].update(time=.2),
            'bool_step':lambda x:x['frames'][0].update(step=False),
            'missing_initial':lambda x:x['frames'].pop(0),
            'fake_final':lambda x:x['frames'][-1]['positions'][0].__setitem__(2,.6),
            'wrong_shape':lambda x:x['frames'][0]['positions'][0].append(3),
            'bad_quaternion':lambda x:x['frames'][0]['rotations'][0].__setitem__(3,2),
            'wrong_scale':lambda x:x['bodies'][0].update(scale=True),
            'unknown_sampling':lambda x:x['sampling'].update(interpolation=True)}
        for name,mutate in variants.items():
            bad=copy.deepcopy(data);mutate(bad)
            with self.subTest(name=name),self.assertRaises((ValueError,TypeError)):motion.validate(raw(bad),result,'d'*64,'b'*64)
        with self.assertRaises(ValueError):motion.decode(b'x'*(motion.MAX_BYTES+1))
        with self.assertRaisesRegex(ValueError,'Duplicate'):motion.decode(b'{"x":1,"x":2}')
        with self.assertRaises(ValueError):motion.validate(raw(data),result,'f'*64,'b'*64)
    def test_periodic_timestamp_and_no_bodies(self):
        _,result=example();result['physics_input_format_version']=3;result['steps']=16*3
        data,_=example(result)
        self.assertEqual([f['step'] for f in data['frames']],[0,2,3])
        self.assertEqual(motion.validate(raw(data),result,'d'*64,'b'*64)['duration_seconds'],.05)
        bad=copy.deepcopy(data);bad['sampling']['substeps']=1
        with self.assertRaises(ValueError):motion.validate(raw(bad),result,'d'*64,'b'*64)
        result.update(poses=[],steps=0);data,_=example(result)
        self.assertFalse(motion.validate(raw(data),result,'d'*64,'b'*64)['available'])
    def test_real_blobs_saved2_reuses_original_motion_no_physics_or_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs=Path(directory)/'jobs';fixture=synthetic_current(jobs,version=2)
            data,result=example(fixture['result'],motion.digest((fixture['run']/'result.json').read_bytes()))
            path=fixture['run']/'motion-v1.json';path.write_bytes(raw(data));before=path.read_bytes()
            candidate=dict(job_id=result['job_id'],result=result)
            one=motion.collect(jobs,candidate);self.assertEqual(one['raw'],before)
            previous=fixture
            for identity in ('2'*32,'3'*32):
                previous=saved(previous,identity);current=dict(job_id=identity,result=previous['result'])
                saved_motion=motion.collect(jobs,current)
                self.assertEqual(saved_motion['raw'],before);self.assertEqual(saved_motion['metadata']['source_job_id'],result['job_id'])
                self.assertEqual(path.read_bytes(),before)
            path.write_bytes(before+b' ')
            # Raw JSON changes alone are not rebaselined after adoption: watch SHA is pinned.
            self.assertNotEqual(motion.digest(path.read_bytes()),one['watch'][str(path)][0])
            path.unlink()
            self.assertFalse(motion.collect(jobs,current)['metadata']['available'])
            outside=Path(directory)/'outside'
            with self.assertRaises(ValueError):motion.owned(outside,jobs)
    def test_graph_snapshot_motion_is_job_pinned_copied_and_old_snapshots_compatible(self):
        import designer_review as D
        data,result=example();motion_raw=raw(data)
        # Reuse actual immutable HNC/geometry only as a container; all changed values are TEST_ONLY.
        initial=D.source_files();job=initial[0];files=copy.deepcopy(initial[1]);display=copy.deepcopy(initial[3])
        result['job_id']=job;result['pose_origin']['job_id']=job;data,result=example(result)
        source_raw=raw(result);data['result_sha256']=motion.digest(source_raw);files['raw/motion-v1.json']=raw(data);files['raw/motion-origin-result.json']=source_raw
        files['raw/physics_inputs.json']=b'TEST_ONLY physical bytes';result['physics_input_hash']=motion.digest(files['raw/physics_inputs.json']);data['physics_input_hash']=result['physics_input_hash']
        source_raw=raw(result);data['result_sha256']=motion.digest(source_raw);files['raw/motion-v1.json']=raw(data);files['raw/motion-origin-result.json']=source_raw
        display['motion']=motion.validate(raw(data),result,motion.digest(source_raw),result['physics_input_hash'])
        with tempfile.TemporaryDirectory() as directory,patch.object(D,'check_source_watch'):
            work=Path(directory);D._commit(work,(job,files,{},display,*initial[4:]));loaded=D.load(work,job)
            self.assertEqual(loaded['motion'],files['raw/motion-v1.json'])
            self.assertIn('?job='+job,loaded['display']['motion']['data_url'])
            manifest=work/'designer-review'/job/'raw/motion-v1.json';manifest.write_bytes(b'{}')
            with self.assertRaises(ValueError):D.load(work,job)
    def test_native_observer_hooks_leave_stepper_and_result_protocol_closed(self):
        source=(ROOT/'worker/main.cpp').read_text(encoding='utf8')
        self.assertIn('motion_v1::publish(motion_data',source)
        self.assertIn('std::ifstream raw_result',source);self.assertIn('actual_result_bytes',source)
        self.assertIn('controller->finish();displacement_guard',source)
        self.assertIn('recorder->observe(observed_poses(),observed_steps)',source)
        self.assertNotIn('result["motion"]',source)
        helper=(ROOT/'worker/motion.h').read_text(encoding='utf8')
        self.assertNotIn('SetPosition',helper);self.assertNotIn('Update(',helper)
        self.assertIn('CREATE_NEW',helper);self.assertIn('raw.size()>MAX_BYTES',helper)
    def test_compiled_identities_and_job_pinned_GET_bytes(self):
        from starlette.responses import Response
        data,_=example();payload=raw(data);metadata=motion.absent();metadata.update(available=True,status='available')
        bundle=dict(motion=dict(raw=payload,metadata=metadata))
        tree=ast.parse((ROOT/'local_review/server.py').read_text(encoding='utf8'))
        functions=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in ('motion_metadata','motion_data')]
        for function in functions:function.decorator_list=[]
        seen=[]
        def selected(job):seen.append(job);return bundle
        env=dict(selected_bundle=selected,motion=motion,Response=Response,HTTPException=RuntimeError)
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<actual job-pinned GET functions>','exec'),env)
        self.assertEqual(asyncio.run(env['motion_data']('1'*32)).body,payload)
        self.assertIn('/'+'1'*32+'/',asyncio.run(env['motion_metadata']('1'*32))['data_url'])
        self.assertEqual(seen,['1'*32,'1'*32])
        for mode in ('legacy','pbr','periodic'):
            directory=ROOT/'build-review-motion';fp=(directory/(mode+'-build-fingerprint.txt')).read_text().strip()
            self.assertEqual(motion.PRODUCERS[fp],motion.digest((directory/'Release'/('scatter_worker_'+mode+'_motion.exe')).read_bytes()))


if __name__=='__main__':unittest.main()
