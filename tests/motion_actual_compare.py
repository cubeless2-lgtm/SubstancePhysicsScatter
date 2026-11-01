"""Root-only real worker comparison against preserved actual output; no promotion."""
from pathlib import Path
import copy,hashlib,json,shutil,subprocess,sys,uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import motion

def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.write_bytes((json.dumps(value,indent=2)+'\n').encode('utf8'))
def rebase(value,old,new):
    if isinstance(value,str):return value.replace(str(old),str(new))
    if isinstance(value,list):return [rebase(x,old,new) for x in value]
    if isinstance(value,dict):return {k:rebase(v,old,new) for k,v in value.items()}
    return value

if __name__=='__main__':
    work=ROOT/'output/evidence/motion-actual'/uuid.uuid4().hex;work.mkdir(parents=True)
    example=ROOT/'output/GraphMaskReview/88eed9b1aa994942882ee8ce7393919e'
    target=example/'Scatter_PhysicsScatter/scatter_edf936a1bb4a4b99a40cb22a541cbbde'
    current=json.loads((target/'current.json').read_bytes())
    legacy=target/'runs'/current['result']['pose_origin']['job_id']
    normal=ROOT/'local_review/workspace/jobs/runs'
    inputs=[('legacy',legacy),('pbr',normal/'00536d2122ab4f8a854d41eeef043ebc'),('periodic',normal/'951ac861c03a4802b52bf6f59a34b0a3')]
    report=dict(status='RUNNING',promotions=0,cases=[]);write(work/'report.json',report)
    for mode,old in inputs:
        baseline=json.loads((old/'result.json').read_bytes());request=json.loads((old/'request.json').read_bytes())
        if request['operation']!='simulate_bake':raise ValueError('Actual original Sim required')
        new=work/mode/'runs'/old.name;new.mkdir(parents=True)
        if (old/'inputs').exists():shutil.copytree(old/'inputs',new/'inputs')
        shutil.copyfile(old/'physics_inputs.json',new/'physics_inputs.json')
        request=rebase(request,old,new);request['output_directory']=str(new);request['physics_inputs_path']=str(new/'physics_inputs.json')
        if request.get('review_v1'):
            manifest=Path(request['review_v1']['manifest_path']);write(manifest,rebase(json.loads(manifest.read_bytes()),old,new))
            request['review_v1']['manifest_sha256']=sha(manifest.read_bytes())
        write(new/'request.json',request)
        exe=ROOT/f'build-review-motion/Release/scatter_worker_{mode}_motion.exe'
        process=subprocess.run([str(exe),str(new/'request.json')],capture_output=True,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
        (new/'stdout.jsonl').write_bytes(process.stdout);(new/'stderr.txt').write_bytes(process.stderr)
        if process.returncode:raise RuntimeError(process.stdout.decode('utf8')[-2000:]+process.stderr.decode('utf8')[-2000:])
        events=[json.loads(line) for line in process.stdout.splitlines()];assert events[-1]['event']=='completed'
        raw=(new/'result.json').read_bytes();result=json.loads(raw)
        assert result['poses']==baseline['poses'] and result['steps']==baseline['steps'] and result['initial_positions']==baseline['initial_positions']
        assert result['physics_input_hash']==baseline['physics_input_hash']
        maps={p.name:sha(p.read_bytes()) for p in old.glob('*.png')}
        assert maps and all((new/name).read_bytes()==(old/name).read_bytes() for name in maps)
        observed=(new/'motion-v1.json').read_bytes();metadata=motion.validate(observed,result,sha(raw),result['physics_input_hash']);data=motion.decode(observed)
        assert any(f['positions']!=data['frames'][0]['positions'] for f in data['frames'][1:])
        report['cases'].append(dict(mode=mode,baseline=str(old),new=str(new),poses_exact=True,initial_positions_exact=True,steps_exact=True,physics_hash_exact=True,png_bytes_exact=maps,motion=metadata,motion_bytes=len(observed),real_movement=True,initial_frame_is_actual_Jolt=True,initial_frame_matches_planned_spawn=data['frames'][0]['positions']==result['initial_positions']))
        write(work/'report.json',report);print(mode,'PASS',len(result['poses']),len(data['frames']),flush=True)
    report['status']='PASS';write(work/'report.json',report);print(work/'report.json',flush=True)
