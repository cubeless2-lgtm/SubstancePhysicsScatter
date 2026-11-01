"""Fixed current-settings actual Panel run. No graph edit or Panel replacement."""
from pathlib import Path
import copy,importlib,json,runpy,time,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/motion-actual'/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/'report.json';E=dict(status='scheduled',operation='bake' if globals().get('SAVED') else 'simulate_bake')
def publish():REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
publish()
from substance_physics_scatter import ui,lifecycle,motion
importlib.reload(motion)
from PySide6 import QtCore
import shiboken6
state=lifecycle.qt_registry();panel=state['panel'];presentation=state['presentation']
if panel is None or panel._phase!='idle' or panel._token is not None or panel.process is not None:raise ValueError('Canonical Panel must be idle')
snapshot=runpy.run_path(str(ROOT/'tests/designer_prepare_graph_review.py'),run_name='_motion_snapshot')['panel_snapshot']
before=snapshot(panel);previous=copy.deepcopy(panel.jobs.current);pointer=shiboken6.getCppPointer(panel)[0]
E['before_settings']=before
settings=copy.deepcopy(before);settings.pop('previous_current',None)
importlib.reload(ui)
expected=ROOT/'build-review-motion/Release/scatter_worker_legacy_motion.exe'
if ui.worker_path()!=expected:raise ValueError('Motion worker selection differs')
started=time.monotonic();panel.run(bool(globals().get('SAVED')))
E.update(previous_job=previous['job_id'],panel_pointer=pointer,worker=str(expected));publish()
timer=QtCore.QTimer();timer.setInterval(100)
def finish():
    try:
        if time.monotonic()-started>90:raise TimeoutError('Panel actual run timeout; no retry')
        if panel._token is not None or panel.process is not None or panel._phase!='idle':return
        timer.stop();after=snapshot(panel);E['after_settings']=copy.deepcopy(after);after.pop('previous_current',None)
        if E['operation']=='bake':
            # Existing Saved canonicalizes only the displayed snapshot filename.
            current=panel.jobs.current
            actual_name=current['request'].get('scatter_mask',{}).get('source_name')
            if after.get('mask',{}).get('source_name')!=actual_name:raise ValueError('Saved mask name differs from its actual request')
            settings.get('mask',{}).update(source_name=actual_name)
        if after!=settings or shiboken6.getCppPointer(panel)[0]!=pointer:raise ValueError('Panel settings or identity changed')
        current=panel.jobs.current
        if current['job_id']==previous['job_id'] or current['request']['operation']!=E['operation']:raise ValueError('New expected completed job not selected')
        observed=motion.collect(panel.jobs.directory,current)
        if not observed['metadata']['available']:raise ValueError('Actual Jolt observations unavailable')
        if E['operation']=='bake' and (current['result']['poses']!=previous['result']['poses'] or current['result']['execution']['physics_executed'] is not False):raise ValueError('Saved reran physics or changed poses')
        if E['operation']=='simulate_bake' and current['result']['execution']['physics_executed'] is not True:raise ValueError('Simulation did not run physics')
        E.update(status='PASS',job=current['job_id'],motion=observed['metadata'],panel_settings_unchanged=True,panel_identity_unchanged=True,execution=current['result']['execution'],separate=presentation.separate,window_geometry=[presentation.window.x(),presentation.window.y(),presentation.window.width(),presentation.window.height()])
        publish()
    except BaseException:
        timer.stop();E.update(status='FAILED',traceback=__import__('traceback').format_exc());publish()
timer.timeout.connect(finish);timer.start()
state['_motion_actual_timer']=timer
