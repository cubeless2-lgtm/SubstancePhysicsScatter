"""Real Qt multipart + Panel shutdown barrier against a fixed isolated HTTP fixture."""
from pathlib import Path
import hashlib,importlib,json,threading,time,traceback,types,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];WORK=ROOT/'output/designer_bridge/settings-upload-shutdown'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json';report={'status':'scheduled','work':str(WORK)}
def write():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
write()
from PySide6 import QtCore
from substance_physics_scatter import ui,lifecycle,viewer_identity,viewer_runtime,viewer_settings
for module in (viewer_identity,viewer_runtime,viewer_settings,ui):importlib.reload(module)
registry=lifecycle.qt_registry();canonical=registry.get('panel')
if canonical is not None and (canonical._token is not None or canonical.process is not None or canonical._phase!='idle'):raise ValueError('Canonical panel must be idle')
state={'panel':None,'dialog':None,'timer':None,'server':None,'server_thread':None,'phase':'setup','started':time.monotonic(),'acks':[],'posted':threading.Event(),'release':threading.Event()}
png_sha='a'*64
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*_):pass
 def respond(self,status,value):
  raw=json.dumps(value,separators=(',',':')).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path=='/api/viewer-health':self.respond(200,dict(application=viewer_identity.APPLICATION,protocol_version=viewer_identity.PROTOCOL_VERSION,project_root_sha256=viewer_identity.root_sha256(ROOT),authentication=viewer_identity.AUTHENTICATION,process_id=123));return
  if self.path=='/api/state':self.respond(200,dict(session_token='a'*64,operation_busy=False,current=None,assets=[],capabilities={}));return
  if self.path=='/api/designer-draft-state':self.respond(200,dict(revision=None,current_job_id=None));return
  self.respond(404,{'detail':'unknown'})
 def do_POST(self):
  if self.path!='/api/assets':self.respond(404,{'detail':'unknown'});return
  if self.headers.get('X-Review-Token')!='a'*64:self.respond(403,{'detail':'token'});return
  size=int(self.headers.get('Content-Length','0'));body=self.rfile.read(size)
  state['upload_bytes']=len(body);state['contains_fixture']=b'v 0 0 0' in body;state['posted'].set()
  if not state['release'].wait(20):self.respond(500,{'detail':'test deadline'});return
  self.respond(200,dict(asset_id='b'*32,enabled=True,name='fixture.obj',render_revision='c'*64,material_revision='d'*64,metadata={'files':{'physics.obj':'e'*64},'materials':[],'warnings':[],'material_ready':False}))
def finish(status,error=None):
 if state['timer'] is not None:state['timer'].stop()
 state['release'].set()
 if state['server'] is not None:
  try:state['server'].shutdown();state['server'].server_close()
  except BaseException as e:status='FAIL';report['server_cleanup_error']=repr(e)
 panel=state['panel']
 if panel is not None:
  try:
   if panel._token is not None or panel.process is not None or getattr(panel,'_settings_shutdown_pending',False):raise ValueError('Own panel shutdown remains pending')
   panel.deleteLater()
  except BaseException as e:status='FAIL';report['panel_cleanup_error']=repr(e)
 if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
 report['status']=status
 if error:report['traceback']=error
 write();registry.pop('_settings_upload_shutdown_actual',None)
def poll():
 try:
  if time.monotonic()-state['started']>45:raise TimeoutError('Qt upload shutdown smoke timed out')
  panel=state['panel'];dialog=state['dialog']
  if state['phase']=='load':
   if not dialog.ready or dialog.reply is not None:return
   fixture=WORK/'fixture.obj';fixture.write_bytes(b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n');state['fixture']=fixture;state['fixture_sha']=hashlib.sha256(fixture.read_bytes()).hexdigest()
   dialog.upload_assets([str(fixture)]);state['phase']='upload';return
  if state['phase']=='upload':
   if not state['posted'].is_set():return
   if dialog.reply is None or dialog.upload_temp is None or not state.get('contains_fixture'):raise ValueError('Real Qt streamed multipart not observed')
   state['temp_path']=dialog.upload_temp.name
   panel.request_shutdown(lambda:state['acks'].append(1));panel.request_shutdown(lambda:state['acks'].append(2))
   if state['acks']:raise ValueError('Panel shutdown acknowledged before HTTP response')
   state['phase']='wait';state['release'].set();return
  if state['phase']=='wait':
   if len(state['acks'])<2:return
   if state['acks']!=[1,2] or getattr(panel,'_settings_shutdown_pending',False) or getattr(panel,'_viewer_settings_dialog',None) is not None:raise ValueError('Panel shutdown acknowledgement/cleanup differs')
   if Path(state['temp_path']).exists():raise ValueError('Owned upload temporary directory remains')
   if hashlib.sha256(state['fixture'].read_bytes()).hexdigest()!=state['fixture_sha']:raise ValueError('Original fixture changed')
   report.update(actual_qt_streamed_multipart=True,post_bytes=state['upload_bytes'],ack_delayed_until_response=True,acks_once_each=True,temp_removed=True,source_preserved=True,canonical_panel_preserved=True)
   finish('PASS')
 except BaseException:finish('FAIL',traceback.format_exc())
try:
 if not viewer_runtime.port_is_unbound(8894):raise ValueError('Isolated test port already in use')
 server=ThreadingHTTPServer(('127.0.0.1',8894),Handler);state['server']=server
 thread=threading.Thread(target=server.serve_forever,daemon=True);state['server_thread']=thread;thread.start()
 panel=ui.Panel();state['panel']=panel;panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8894/',panel)
 dialog=viewer_settings.open_viewer_settings(panel,expected_root=ROOT);state['dialog']=dialog
 timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(50);timer.timeout.connect(poll);registry['_settings_upload_shutdown_actual']=state
 state['phase']='load';timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
