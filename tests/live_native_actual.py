"""Root-owned actual LIVE comparison. Existing successful outputs are preserved."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,time,uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'plugin'))
from motion_actual_compare import rebase,write
from substance_physics_scatter import live_preview
NATIVE_PINS={
 'legacy':('910ac079f0c003a38a80d6ad5792b26262a9df3293e62de2b46a9eee54f118a1','2c7bc9a8f790f407f0a962b5729a47b09df8ffeaa326e68295558ec337204cbf'),
 'pbr':('1b613147a7c08a2b91202cd3bab84a5c4eb5dd6bb20e8ab9cec98cb272f358d2','e2fe4cbabd63f46c10f0b728d48e2fa9a07cee4686d0978217d202aa8abd5a96'),
 'periodic':('c70ff545e18c153679a2d45e3a6848f6a59effd2f4a001c84682be8d61a19a79','6b48cb93dd09e2f1035ae7919cd9815dc91d8e164d5f6003be420041cef74320')}

if __name__=='__main__':
    modes=sys.argv[1:] or ['legacy','pbr','periodic']
    if any(m not in ('legacy','pbr','periodic') for m in modes):raise ValueError('Fixed native mode required')
    work=ROOT/'output/evidence/live-native'/uuid.uuid4().hex;work.mkdir(parents=True)
    report=dict(status='RUNNING',cases=[],promotions=0);write(work/'report.json',report)
    def failed(kind,value,traceback):
        report.update(status='FAILED',error=str(value));write(work/'report.json',report)
        sys.__excepthook__(kind,value,traceback)
    sys.excepthook=failed
    graph=ROOT/'output/GraphMaskReview/88eed9b1aa994942882ee8ce7393919e/Scatter_PhysicsScatter/scatter_edf936a1bb4a4b99a40cb22a541cbbde'
    current=json.loads((graph/'current.json').read_bytes())
    old_paths={'legacy':graph/'runs'/current['result']['pose_origin']['job_id'],
               'pbr':ROOT/'local_review/workspace/jobs/runs/00536d2122ab4f8a854d41eeef043ebc',
               'periodic':ROOT/'local_review/workspace/jobs/runs/951ac861c03a4802b52bf6f59a34b0a3'}
    for mode in modes:
        old=old_paths[mode];baseline=json.loads((old/'result.json').read_bytes());request=json.loads((old/'request.json').read_bytes())
        if request['operation']!='simulate_bake':raise ValueError('Actual original simulation required')
        run=work/mode/'runs'/old.name;run.mkdir(parents=True)
        if (old/'inputs').exists():shutil.copytree(old/'inputs',run/'inputs')
        shutil.copyfile(old/'physics_inputs.json',run/'physics_inputs.json')
        request=rebase(request,old,run);request.update(output_directory=str(run),physics_inputs_path=str(run/'physics_inputs.json'))
        if request.get('review_v1'):
            manifest=Path(request['review_v1']['manifest_path']);write(manifest,rebase(json.loads(manifest.read_bytes()),old,run))
            request['review_v1']['manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
        write(run/'request.json',request)
        exe=ROOT/f'build-review-live-ready1/Release/scatter_worker_{mode}_live.exe'
        binary_sha=hashlib.sha256(exe.read_bytes()).hexdigest()
        expected_fp,expected_sha=NATIVE_PINS[mode];assert binary_sha==expected_sha
        nonce=uuid.uuid4().hex;env=dict(os.environ,SCATTER_LIVE_PREVIEW='1',SCATTER_LIVE_NONCE=nonce,SCATTER_LIVE_WAIT_READY='1')
        observations=[];seen=set();started=time.monotonic();acknowledged=False
        with (run/'stdout.jsonl').open('xb') as stdout,(run/'stderr.txt').open('xb') as stderr:
            process=subprocess.Popen([str(exe),str(run/'request.json')],env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                while process.poll() is None:
                    if time.monotonic()-started>190:raise TimeoutError('Owned worker live timeout')
                    path=run/'live-frame-v1.json'
                    if path.exists():
                        raw=live_preview.read(path,8*1024*1024);assert len(raw)<=8*1024*1024
                        frame=json.loads(raw)
                        assert frame['producer']['binary_sha256']==expected_sha and frame['producer']['build_fingerprint']==expected_fp
                        assert frame['job_id']==request['job_id'] and frame['nonce']==nonce and frame['process_id']==process.pid
                        assert frame['physics_input_hash']==request['physics_input_hash'] and frame['coordinate_system']=='RH_Z_UP' and frame['units']=='meters'
                        step=frame['step'];hz=60 if mode=='periodic' else 120
                        assert frame['time']==step/hz and frame['sequence']==step+1
                        if not acknowledged:
                            assert frame['step']==0 and frame['ready_status']=='waiting'
                            ack_temp=run/'live-ready-v1.test.tmp';write(ack_temp,dict(schema_version=1,job_id=request['job_id'],nonce=nonce,sequence=1));ack_temp.replace(run/'live-ready-v1.json');acknowledged=True
                        if frame['sequence'] not in seen:
                            if observations:assert frame['sequence']>observations[-1]['sequence']
                            seen.add(frame['sequence']);observations.append(dict(sequence=frame['sequence'],step=step,time=frame['time'],phase=frame['phase'],wall_seconds=time.monotonic()-started,process_running=True,result_absent=not (run/'result.json').exists(),positions=frame['positions'],rotations=frame['rotations']))
                    time.sleep(.01)
                process.wait()
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=10)
        assert process.returncode==0,(run/'stdout.jsonl').read_text(encoding='utf8')[-2000:]
        result=json.loads((run/'result.json').read_bytes())
        for key in ('poses','initial_positions','steps','physics_input_hash'):assert result[key]==baseline[key],key
        pngs=[p.name for p in old.glob('*.png')];assert pngs
        assert all((run/name).read_bytes()==(old/name).read_bytes() for name in pngs)
        moving=[f for f in observations if f['phase']=='simulate' and f['result_absent']]
        assert acknowledged and len(moving)>=3 and moving[0]['positions']!=moving[-1]['positions']
        assert frame['ready_status']=='acknowledged'
        assert moving[-1]['wall_seconds']>=moving[-1]['time']
        write(run/'observed-running-frames.json',observations)
        report['cases'].append(dict(mode=mode,run=str(run),producer=frame['producer'],frames_while_process_running=len(moving),first_time=moving[0]['time'],last_time=moving[-1]['time'],actual_movement=True,final_poses_exact=True,PNG_bytes_exact=pngs,recorded_observation=str(run/'observed-running-frames.json')))
        write(work/'report.json',report);print(mode,'PASS',len(moving),'frames before result',flush=True)
    report['status']='PASS';write(work/'report.json',report);print(work/'report.json',flush=True)
