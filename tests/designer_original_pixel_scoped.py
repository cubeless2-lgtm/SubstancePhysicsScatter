"""Re-use the original N/F0/T/F1 oracle under a scoped SDK transaction."""
from pathlib import Path
import hashlib,json,traceback,uuid

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/graph-mask-native-noise-raw-probe/7d616be94c1b428a9a814d0367a12acc'
WORK=ROOT/'output/evidence/original-pixel-scoped'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json'
result=dict(status='running',tolerance=0,computer_use=False,original_failures_preserved=True)
def write():
    temp=REPORT.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2),encoding='utf8');temp.replace(REPORT)
write()
try:
    from substance_physics_scatter.evaluation import compute_graph,evaluation_scope
    from substance_physics_scatter.errors import HOST_ERRORS
    run_path=BASE/'run_probe.py';lane_path=BASE/'compute_lane.py'
    source=run_path.read_text(encoding='utf8');lane_source=lane_path.read_text(encoding='utf8')
    needle='role["graph"].compute()'
    loader='lane=runpy.run_path(str(BASE/"compute_lane.py"))'
    if lane_source.count(needle)!=1 or source.count(loader)!=1:raise ValueError('Fixed historical compute/loader anchor differs')
    patched_lane=lane_source.replace(needle,'compute_graph(role["graph"])')
    patched_run=source.replace(loader,'lane=_SCOPED_LANE')
    lane={'__file__':str(lane_path),'__name__':'_scoped_original_pixel_lane','compute_graph':compute_graph}
    exec(compile(patched_lane,str(lane_path),'exec'),lane)
    namespace={'__file__':str(run_path),'__name__':'__main__','_SCOPED_LANE':lane,'COORDINATOR_CONFIRMED_IDLE_SAME_SESSION':True}
    result['adaptation']={
        'original_run_sha256':hashlib.sha256(source.encode('utf8')).hexdigest(),
        'original_lane_sha256':hashlib.sha256(lane_source.encode('utf8')).hexdigest(),
        'patched_run_sha256':hashlib.sha256(patched_run.encode('utf8')).hexdigest(),
        'patched_lane_sha256':hashlib.sha256(patched_lane.encode('utf8')).hexdigest(),
        'compute_call_replacements':1,'loader_replacements':1,'historical_files_modified':False,
        'oracle':'F0=N, F1=N, T=65535-N; unchanged',
        'scope':'Temporary CPU affinity covers private creation, setters, compute, readback and cleanup; exact restoration on exit'}
    try:
        with evaluation_scope():
            exec(compile(patched_run,str(run_path),'exec'),namespace)
        path=Path(namespace['WORK'])/'summary.json'
        observed=json.loads(path.read_text(encoding='utf8'))
        result.update(status='observation_complete',legacy_report=str(path),observation=observed)
    except HOST_ERRORS:
        result.update(status='error',traceback=traceback.format_exc())
except Exception:
    result.update(status='error',traceback=traceback.format_exc())
write()
