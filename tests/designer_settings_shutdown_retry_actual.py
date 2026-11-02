"""Actual Qt shutdown retry after one temporary cleanup failure."""
from pathlib import Path
import importlib,json,time,traceback,types,uuid
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'output/settings-shutdown-retry'/uuid.uuid4().hex[:12];WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json';report={'status':'scheduled','work':str(WORK)}
def write():REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
write()
from PySide6 import QtCore
from substance_physics_scatter import ui,viewer_settings,lifecycle
importlib.reload(ui);importlib.reload(viewer_settings)
registry=lifecycle.qt_registry();canonical=registry.get('panel')
state={'panel':None,'dialog':None,'timer':None,'phase':'load','started':time.monotonic(),'acks':[]}
class FlakyTemporary:
 def __init__(self):self.calls=0
 def cleanup(self):
  self.calls+=1
  if self.calls==1:raise PermissionError('injected transient lock')
def finish(status,error=None):
 if state['timer'] is not None:state['timer'].stop()
 panel=state['panel'];dialog=state['dialog']
 if dialog is not None and (dialog.reply is not None or dialog.upload_future is not None):report.update(status='FAIL',error='In-flight dialog preserved');write();return
 if panel is not None:
  try:panel.close();panel.deleteLater()
  except BaseException as e:status='FAIL';report['cleanup_error']=repr(e)
 if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
 report['status']=status
 if error:report['traceback']=error
 write();registry.pop('_settings_shutdown_retry_actual',None)
def poll():
 try:
  if time.monotonic()-state['started']>40:raise TimeoutError('shutdown retry deadline')
  panel=state['panel'];dialog=state['dialog']
  if state['phase']=='load':
   if dialog.reply is not None:return
   if not dialog.ready:raise ValueError('Viewer not ready: '+dialog.status.text())
   temporary=FlakyTemporary();state['temporary']=temporary;dialog.upload_temp=temporary
   panel.request_shutdown(lambda:state['acks'].append('first'));panel.request_shutdown(lambda:state['acks'].append('second'))
   if state['acks'] or temporary.calls!=1 or not panel._settings_shutdown_pending:raise ValueError('Failed cleanup unexpectedly acknowledged')
   state['phase']='retry';dialog.close();return
  if state['phase']=='retry':
   if len(state['acks'])<2:return
   if state['acks']!=['first','second'] or state['temporary'].calls!=2 or panel._settings_shutdown_pending:raise ValueError('Retry acknowledgements or cleanup count differ')
   if panel._viewer_settings_dialog is not None:raise ValueError('Dialog remains attached')
   state['dialog']=None;report.update(transient_failure_blocked_ack=True,retry_acknowledged_once=True,cleanup_attempts=state['temporary'].calls,acks=state['acks'],canonical_preserved=True);finish('PASS')
 except BaseException:finish('FAIL',traceback.format_exc())
try:
 panel=ui.Panel();state['panel']=panel;panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8879/',panel)
 state['dialog']=viewer_settings.open_viewer_settings(panel,expected_root=ROOT)
 timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(100);timer.timeout.connect(poll);registry['_settings_shutdown_retry_actual']=state;timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
