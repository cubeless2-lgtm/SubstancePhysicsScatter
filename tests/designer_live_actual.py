"""Root-owned actual existing-Panel LIVE check. No settings or graph edits."""
from pathlib import Path
import copy,importlib,json,runpy,time,types,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/live-actual'/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/'report.json';E=dict(status='scheduled',observations=[])
def publish():REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
publish()
from substance_physics_scatter import ui,lifecycle,motion,live_preview
from substance_physics_scatter.fileio import io_path
from PySide6 import QtCore
import shiboken6
state=lifecycle.qt_registry();panel=state.get('panel')
if panel is None or panel._phase!='idle' or panel._token is not None or panel.process is not None:raise ValueError('Canonical Panel must be idle')
snapshot=runpy.run_path(str(ROOT/'tests/designer_prepare_graph_review.py'),run_name='_live_snapshot')['panel_snapshot']
before=snapshot(panel);previous=copy.deepcopy(panel.jobs.current);pointer=shiboken6.getCppPointer(panel)[0]
E.update(before_settings=before,previous_job=previous['job_id'],panel_pointer=pointer)
importlib.reload(live_preview);importlib.reload(motion);importlib.reload(ui)
# Explicit non-super methods only. Extra newly introduced live helpers are grafted by name.
names={'run','_prepare_and_start','_end','_finish','stop','_process_error','_ensure_live'}|{n for n in ui.Panel.__dict__ if n.startswith('_live')}
for name in sorted(names):
    value=ui.Panel.__dict__.get(name)
    if isinstance(value,types.FunctionType):setattr(panel,name,types.MethodType(value,panel))
expected=ROOT/'build-review-live-ready1/Release/scatter_worker_legacy_live.exe'
if ui.worker_path()!=expected:raise ValueError('LIVE native path differs')
started=time.monotonic();seen=set();active_job=None
timer=QtCore.QTimer();timer.setInterval(16)
def finish():
    global active_job
    try:
        if time.monotonic()-started>90:raise TimeoutError('Existing Panel LIVE deadline; no automatic retry')
        process=panel.process
        if process is not None and process.processId()>0 and panel.jobs.active is not None:
            active_job=panel.jobs.active['job_id'];path=io_path(Path(panel.jobs.directory)/'runs'/active_job/'live-frame-v1.json')
            if path.exists():
                raw=live_preview.read(path,8*1024*1024)
                if len(raw)>8*1024*1024:raise ValueError('Actual LIVE frame byte limit')
                frame=json.loads(raw)
                if frame['job_id']!=active_job or frame['process_id']!=process.processId():raise ValueError('Actual LIVE child identity differs')
                if frame['phase']=='simulate' and frame['sequence'] not in seen and len(E['observations'])<64:
                    if panel.jobs.current['job_id']!=previous['job_id'] or io_path(Path(panel.jobs.directory)/'runs'/active_job/'result.json').exists():raise ValueError('LIVE observation must precede result and promotion')
                    seen.add(frame['sequence']);E['observations'].append(dict(sequence=frame['sequence'],step=frame['step'],time=frame['time'],positions=frame['positions'],rotations=frame['rotations'],process_running=True,result_absent=True));publish()
        if panel._token is not None or panel.process is not None or panel._phase!='idle':return
        timer.stop();current=panel.jobs.current
        if not active_job or current['job_id']!=active_job or current['result']['execution']['physics_executed'] is not True:raise ValueError('Actual LIVE new simulation not selected')
        observations=E['observations']
        if len(observations)<3 or observations[0]['positions']==observations[-1]['positions']:raise ValueError('No multiple moving frames during live calculation')
        after=snapshot(panel);E['after_settings']=copy.deepcopy(after)
        wanted=copy.deepcopy(before);wanted.pop('previous_current',None);after.pop('previous_current',None)
        for name in ('content_hash','source_name'):
            actual=current['request'].get('scatter_mask',{}).get(name)
            if after.get('mask',{}).get(name)!=actual:raise ValueError('Capture mask metadata differs from real request')
            wanted.get('mask',{}).update({name:actual})
        if after!=wanted or shiboken6.getCppPointer(panel)[0]!=pointer:raise ValueError('Panel user settings or identity changed')
        observed=motion.collect(panel.jobs.directory,current)
        if not observed['metadata']['available']:raise ValueError('Completed recording absent')
        final=json.loads(io_path(Path(panel.jobs.directory)/'runs'/active_job/'live-frame-v1.json').read_bytes())
        if final.get('ready_status')!='acknowledged':raise ValueError('Actual Graph viewer did not acknowledge its first rendered scene')
        if final['positions']!=[p['position'] for p in current['result']['poses']] or final['rotations']!=[p['rotation'] for p in current['result']['poses']]:raise ValueError('LIVE final pose differs from completed result')
        E.update(status='PASS',job=active_job,moving_frames_before_result=len(observations),viewer_ready_acknowledged=True,final_pose_exact=True,motion=observed['metadata'],settings_preserved=True,elapsed=time.monotonic()-started);publish()
    except BaseException:
        timer.stop();E.update(status='FAILED',traceback=__import__('traceback').format_exc());publish()
timer.timeout.connect(finish);state['_live_actual_timer']=timer
def begin():
    try:panel.run(False);timer.start()
    except BaseException:E.update(status='FAILED',traceback=__import__('traceback').format_exc());publish()
# Give the external screen verifier time to arm before starting the real operation.
QtCore.QTimer.singleShot(10000,begin)
