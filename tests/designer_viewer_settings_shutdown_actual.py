"""Actual Qt panel shutdown barrier while an owned asset snapshot is pending."""
from pathlib import Path
import hashlib,importlib,json,time,traceback,types,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/viewer-settings-shutdown'/uuid.uuid4().hex[:12];WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json';report={'status':'scheduled','work':str(WORK)}
def write():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
def read(path):
 with urllib.request.urlopen('http://127.0.0.1:8879'+path,timeout=5) as response:return json.loads(response.read(2*1024*1024))
def state_value():
 value=read('/api/state');current=value.get('current') or {}
 return dict(job=current.get('job_id'),assets=sorted(x['asset_id'] for x in value.get('assets',[])),draft=read('/api/designer-draft-state'))
write()
from PySide6 import QtCore
from substance_physics_scatter import ui,viewer_settings,lifecycle
importlib.reload(ui);importlib.reload(viewer_settings)
registry=lifecycle.qt_registry();canonical=registry.get('panel')
state={'panel':None,'dialog':None,'timer':None,'phase':'load','acks':[],'started':time.monotonic()}
def finish(status,error=None):
 if state['timer'] is not None:state['timer'].stop()
 panel=state['panel'];dialog=state['dialog']
 if dialog is not None and (dialog.reply is not None or dialog.upload_future is not None):
  report.update(status='FAIL',error='Owned operation still active; panel preserved');write();return
 if panel is not None:
  try:panel.close();panel.deleteLater()
  except BaseException as e:status='FAIL';report['cleanup_error']=repr(e)
 if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
 report['status']=status
 if error:report['traceback']=error
 write();registry.pop('_viewer_settings_shutdown_actual',None)
def poll():
 try:
  if time.monotonic()-state['started']>45:raise TimeoutError('Shutdown smoke exceeded deadline')
  panel=state['panel'];dialog=state['dialog']
  if state['phase']=='load':
   if dialog.reply is not None:return
   if not dialog.ready:raise ValueError('Isolated viewer not ready: '+dialog.status.text())
   state['before']=state_value();source=WORK/'shutdown.obj';source.write_bytes(b'v 0 0 0\n'+b' '*8*1024*1024);state['source']=source;state['source_sha']=hashlib.sha256(source.read_bytes()).hexdigest()
   dialog.upload_assets([str(source)])
   if dialog.upload_future is None:raise ValueError('Background snapshot did not start')
   temp=dialog.upload_temp.name;state['temp']=temp;state['phase']='shutdown'
   panel.request_shutdown(lambda:state['acks'].append('first'));panel.request_shutdown(lambda:state['acks'].append('second'))
   if state['acks']:raise ValueError('Shutdown acknowledged before owned snapshot stopped')
   return
  if state['phase']=='shutdown':
   if len(state['acks'])<2:return
   if state['acks']!=['first','second']:raise ValueError('Shutdown acknowledgements differ')
   if Path(state['temp']).exists():raise ValueError('Owned temporary snapshot remains')
   if state_value()!=state['before']:raise ValueError('Viewer state changed during stopped snapshot')
   if hashlib.sha256(state['source'].read_bytes()).hexdigest()!=state['source_sha']:raise ValueError('Original changed')
   if getattr(panel,'_viewer_settings_dialog',None) is not None:raise ValueError('Dialog not detached after shutdown')
   state['dialog']=None;report.update(snapshot_shutdown=True,acks=state['acks'],temporary_removed=True,viewer_unchanged=True,original_unchanged=True,canonical_preserved=True);finish('PASS')
 except BaseException:finish('FAIL',traceback.format_exc())
try:
 panel=ui.Panel();state['panel']=panel;panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8879/',panel)
 state['dialog']=viewer_settings.open_viewer_settings(panel,expected_root=ROOT)
 timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(100);timer.timeout.connect(poll);registry['_viewer_settings_shutdown_actual']=state;timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
