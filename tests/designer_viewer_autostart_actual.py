"""Start and reuse an owned viewer on isolated port 8893; never touches 8765."""
from pathlib import Path
import importlib,json,socket,time,traceback,types,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/viewer-autostart'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
report={'status':'scheduled','work':str(WORK),'port':8893}
def write():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
write()
from PySide6 import QtCore
from substance_physics_scatter import ui,lifecycle,viewer_runtime
importlib.reload(viewer_runtime);importlib.reload(ui)
registry=lifecycle.qt_registry();canonical=registry.get('panel')
state={'panel':None,'timer':None,'phase':'setup','started':time.monotonic()}
def health():
    with urllib.request.urlopen('http://127.0.0.1:8893/api/viewer-health',timeout=2) as response:return json.loads(response.read(16385))
def finish(status,error=None):
    if state['timer'] is not None:state['timer'].stop()
    panel=state.get('panel')
    if panel is not None:
        proc=getattr(panel,'_viewer_last_owned_process',None)
        if proc is not None:report['owned_launcher_pid']=proc.pid
        try:panel.close();panel.deleteLater()
        except BaseException as e:status='FAIL';report['cleanup_error']=repr(e)
    if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
    report['status']=status
    if error:report['traceback']=error
    write();registry.pop('_viewer_autostart_actual',None)
def poll():
    try:
        if time.monotonic()-state['started']>40:raise TimeoutError('Viewer start deadline')
        panel=state['panel']
        if getattr(panel,'_viewer_start_state',None) is not None:return
        if not panel.viewer_status.text().startswith('Local viewer ready'):raise ValueError(panel.viewer_status.text())
        value=health();viewer_runtime.validate_health(value,ROOT)
        if state['phase']=='start':
            proc=getattr(panel,'_viewer_last_owned_process',None)
            if proc is None or proc.poll() is not None:raise ValueError('Expected our detached launcher to be running')
            state['health_pid']=value['process_id'];state['launcher_pid']=proc.pid
            state['phase']='reuse';panel.viewer_open.click();return
        if state['phase']=='reuse':
            if value['process_id']!=state['health_pid']:raise ValueError('Second open did not reuse the same viewer')
            report.update(viewer_pid=value['process_id'],owned_launcher_pid=state['launcher_pid'],started=True,reused=True,canonical_preserved=True,process_left_running_for_owner_cleanup=True)
            finish('PASS')
    except BaseException:finish('FAIL',traceback.format_exc())
try:
    if not viewer_runtime.port_is_unbound(8893):raise ValueError('Isolated port already occupied; nothing was started')
    panel=ui.Panel();state['panel']=panel;panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8893/',panel)
    state['phase']='start';timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(100);timer.timeout.connect(poll)
    registry['_viewer_autostart_actual']=state
    panel.viewer_open.click();panel.viewer_open.click() # disabled second click must not create a duplicate
    if getattr(panel,'_viewer_start_state',None) is None:raise ValueError('Viewer check did not start')
    timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
