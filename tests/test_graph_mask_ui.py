"""Actual UI handler paths with plain fake controls/processes. No Qt/SDK process.
This checks orchestration, not Designer ABI, event ordering or dock acceptance.
"""
import ast,copy,json,sys,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter import graph_companion,lifecycle
from substance_physics_scatter.errors import HOST_ERRORS,rollback_or_raise

class Value:
    def __init__(self,value=None):self.data=value;self.enabled=True
    def value(self):return self.data
    def text(self):return self.data
    def currentText(self):return self.data
    def currentData(self):return self.data
    def setText(self,value):self.data=value
    def setValue(self,value):self.data=value
    def setCurrentText(self,value):self.data=value
    def setEnabled(self,value):self.enabled=value
    def setVisible(self,value):self.visible=value
    def clear(self):self.items=[]
    def addItems(self,values):self.items=values;self.data=values[0]

class Signal:
    def __init__(self):self.callbacks=[]
    def connect(self,f):self.callbacks.append(f)
    def emit(self,*args):
        for f in self.callbacks:f(*args)

class Process:
    ProcessError=types.SimpleNamespace(FailedToStart='failed')
    ProcessState=types.SimpleNamespace(NotRunning=0)
    def __init__(self,*_):
        self.started=False;self.deleted=False;self.killed=False
        for name in ('readyReadStandardOutput','readyReadStandardError','finished','errorOccurred'):setattr(self,name,Signal())
    def start(self,*args):self.started=True;self.args=args
    def state(self):return int(self.started and not self.killed)
    def kill(self):self.killed=True
    def deleteLater(self):self.deleted=True
    def readAllStandardOutput(self):return b''
    def readAllStandardError(self):return b''

class Widget:
    def closeEvent(self,event):pass

def panel_class(designer,queue):
    tree=ast.parse((ROOT/'plugin/substance_physics_scatter/ui.py').read_text(encoding='utf8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Panel')
    namespace=dict(__name__='pure_graph_ui',__package__='substance_physics_scatter',QtWidgets=types.SimpleNamespace(QWidget=Widget),QtCore=types.SimpleNamespace(QTimer=types.SimpleNamespace(singleShot=lambda _,f:queue.append(f)),QProcess=Process),designer=designer,copy=copy,json=json,uuid=uuid,Path=Path,worker_path=lambda:Path('fake-worker'),HOST_ERRORS=HOST_ERRORS,rollback_or_raise=rollback_or_raise)
    exec(compile(ast.Module(body=[cls],type_ignores=[]),'ui.py','exec'),namespace)
    return namespace['Panel']

class Jobs:
    def __init__(self,path):self.directory=path;self.active=None;self.prepares=[];self.cancelled=[];self.promoted=[];self.fail=False;self.hook=None;self.current=None
    def prepare(self,rows,s,b,**kwargs):
        self.prepares.append(kwargs)
        if self.fail:raise ValueError('prepare failed before active replacement')
        self.active=dict(job_id=uuid.uuid4().hex,assets=[dict(r,content_hash='a'*64) for r in rows],scatter_mask=None)
        if self.hook:self.hook()
        return self.directory/'request.json'
    def cancel(self):self.cancelled.append(self.active['job_id']);self.active=None
    def validate(self,path,job):return dict(job_id=job,result=dict(settling_status='synthetic',maps=dict(clipped_samples=0)))
    def promote(self,candidate):self.promoted.append(candidate);self.active=None

class Handlers(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.queue=[];self.meta={};self.calls=[];self.rollbacks=[]
        self.designer=types.SimpleNamespace(resolve_scatter=lambda target:'canonical-scatter',checked_current=lambda graph,jobs:jobs.current,settings=lambda graph:copy.deepcopy(self.meta),require_metadata_unchanged=lambda graph,expected:None,inspect_terminal_selection=lambda *args:dict(selected_context={'genuine_fixture':True}),capture_terminal=self.capture,verify_metadata_current=lambda *args:None,update=self.update)
        cls=panel_class(self.designer,self.queue);p=cls.__new__(cls);self.p=p
        p._generation=uuid.uuid4().hex;p._token=None;p._phase='idle';p._closing=False;p._lifecycle_stopping=False;p._graph_ui_enabled=True;p._source_revision=1;p._source_selection=dict(terminal_identifier='native_mask');p._source_context={'fixture':'selected'};p._target_identity={'graph_identifier':'scatter'};p._shutdown_acks=[];p._select_again=False
        p.process=None;p.pending_config=None;p.graph='borrowed-target';p.jobs=Jobs(Path(self.temp.name));p.buffer=bytearray();p.completed=None;p._mask_config={'enabled':False}
        p.count=Value(20);p.width=Value(2);p.depth=Value(2);p.seed=Value(123456789);p.seconds=Value(2);p.height=Value(8);p.edges=Value('walls');p.resolution=Value('64');p.normal=Value('OpenGL');p.mesh=Value('');p.scale=Value(.25)
        p.mask_mode=Value('File / no mask');p.source_choices=Value({'terminal_identifier':'native_mask'});p.source_refresh=Value();p.source_inspect=Value();p.source_status=Value();p.mask_snapshot=Value();p.progress=Value();p.simulate=Value();p.rebake=Value();p.cancel=Value();p.editable_controls=[];p.messages=[]
        p.message=p.messages.append;p.mask_config=lambda:{'enabled':False};p.asset_rows=lambda:[dict(asset_id='a'*32,path=str(ROOT/'tests/fixtures/cube.obj'),format='obj',scale=.25,weight=1.)];p.show_preview=lambda _:None
    def tearDown(self):self.temp.cleanup()
    def flush(self):
        while self.queue:self.queue.pop(0)()
    def capture(self,*args):self.calls.append(args);return dict(png={'fixture':1},capture={'fixture':2},operation_authored_payload={'fixture':3},other='must not pass to core')
    def update(self,*args):return lambda:self.rollbacks.append(True)
    def test_gate_default_off_explicit_per_panel_and_file_path(self):
        p=self.p;p._graph_ui_enabled=False;p.inspect_source();self.assertEqual(self.calls,[]);self.assertIsNone(p._token)
        p.enable_graph_ui_for_testing(True);self.assertTrue(p._graph_ui_enabled);self.assertIsNone(p._source_context)
        p.run(False);self.flush();self.assertEqual(p.jobs.prepares[0]['host_mode'],'current_file');self.assertTrue(p.process.started)
    def test_capture_queued_cancel_blocks_prepare_and_old_active_cancel(self):
        p=self.p;p.mask_mode.data='Graph terminal';p.jobs.active={'job_id':'old'}
        p.run(False);self.assertEqual(p._phase,'awaiting_continuation');p.stop();self.flush()
        self.assertEqual(len(self.calls),1);self.assertEqual(p.jobs.prepares,[]);self.assertEqual(p.jobs.active,{'job_id':'old'});self.assertEqual(p.jobs.cancelled,[]);self.assertIsNone(p.process)
    def test_graph_three_fields_fresh_capture_and_source_reselection(self):
        p=self.p;p.mask_mode.data='Graph terminal';p.run(False);self.flush()
        self.assertEqual(set(p.jobs.prepares[0]['captured_mask']),{'png','capture','operation_authored_payload'});self.assertIsNone(p.jobs.prepares[0]['scatter_mask'])
        p.stop();p.process.finished.emit(1,None)
        p._source_selection={};p._source_context={};p.run(False);p.invalidate_source();self.flush()
        self.assertEqual(len(p.jobs.prepares),1);self.assertIsNone(p.process)
    def test_saved_never_inspects_or_captures_and_has_no_external_mask(self):
        p=self.p;p.mask_mode.data='Graph terminal';p._graph_ui_enabled=False;p.run(True);self.flush()
        self.assertEqual(self.calls,[]);self.assertEqual(p.jobs.prepares,[dict(rebake=True,host_mode='saved_input')])
    def test_prepare_failure_keeps_preexisting_active_and_pending(self):
        p=self.p;p.jobs.active={'job_id':'old'};p.jobs.fail=True;p.run(False);self.flush()
        self.assertEqual(p.jobs.active,{'job_id':'old'});self.assertEqual(p.jobs.cancelled,[]);self.assertIsNone(p._token)
    def test_cancel_during_successful_prepare_cancels_only_new_job(self):
        p=self.p;p.jobs.hook=p.stop;p.run(False);self.flush()
        self.assertEqual(len(p.jobs.cancelled),1);self.assertIsNone(p.jobs.active);self.assertIsNone(p.process)
    def test_stale_process_callback_cannot_touch_new_operation(self):
        p=self.p;p.run(False);self.flush();old=p.process;old.errorOccurred.emit('failed');p.run(False);self.flush();new=p.process
        before=copy.deepcopy(p.jobs.active);old.finished.emit(0,None);old.errorOccurred.emit('failed');old.readyReadStandardError.emit()
        self.assertIs(p.process,new);self.assertEqual(p.jobs.active,before)
    def test_metadata_failure_rolls_back_before_promotion(self):
        p=self.p;p.run(False);self.flush();process=p.process;p.completed={'result_path':'fake','job_id':p.jobs.active['job_id']}
        self.designer.verify_metadata_current=lambda *_:(_ for _ in ()).throw(ValueError('metadata mismatch'))
        process.finished.emit(0,None)
        self.assertEqual(self.rollbacks,[True]);self.assertEqual(p.jobs.promoted,[]);self.assertIsNone(p.process)
    def test_shutdown_waits_for_capture_return_and_queued_ack(self):
        p=self.p;p.mask_mode.data='Graph terminal';disposed=[]
        host=types.SimpleNamespace(valid=lambda _:True,hide=lambda _:None,enable=lambda panel,enabled:setattr(panel,'_lifecycle_stopping',not enabled),process=lambda panel:panel.process,shutdown_panel=lifecycle.QtHost.shutdown_panel,clear_process=lambda panel:setattr(panel,'process',None),dispose_child=lambda layout,panel:disposed.append(panel))
        state=dict(panel=p,dock=object(),layout=object(),generation=1,phase='ready');session=lifecycle.Session(state,host)
        def capture(*args):session.shutdown();self.assertEqual(disposed,[]);return self.capture(*args)
        self.designer.capture_terminal=capture;p.run(False)
        self.assertEqual(state['phase'],'stopping');self.assertEqual(disposed,[]);self.flush()
        self.assertEqual(disposed,[p]);self.assertIsNone(state['panel']);self.assertEqual(p.jobs.prepares,[])

class Metadata(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((ROOT/'plugin/substance_physics_scatter/designer.py').read_text(encoding='utf8'))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('verify_metadata_current','checked_current')]
        self.state={};self.ns=dict(__package__='substance_physics_scatter',settings=lambda _:self.state)
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'designer-metadata.py','exec'),self.ns)
        self.ref=dict(path=graph_companion.NAME,sha256='a'*64,schema_version=1)
    def read(self,root,current,*,metadata_ref):
        actual=current.get(graph_companion.KEY,graph_companion.MISSING)
        if metadata_ref is not graph_companion.MISSING:graph_companion.reference(metadata_ref)
        if actual!=metadata_ref:raise ValueError('Reference differs')
    def test_job_reference_missing_null_and_removed_are_distinct(self):
        c=dict(job_id='a'*32);jobs=types.SimpleNamespace(directory='fake',current=c)
        self.state={'current':dict(c)}
        with patch.object(graph_companion,'read',side_effect=self.read):
            self.assertEqual(self.ns['checked_current'](None,jobs),c)
            self.state['current'][graph_companion.KEY]=None
            with self.assertRaises(ValueError):self.ns['checked_current'](None,jobs)
            c[graph_companion.KEY]=self.ref;self.state['current']={'job_id':c['job_id']}
            with self.assertRaises(ValueError):self.ns['checked_current'](None,jobs)
            self.state['current']=dict(c);self.ns['checked_current'](None,jobs)
            self.state['current']['job_id']='b'*32
            with self.assertRaises(ValueError):self.ns['checked_current'](None,jobs)
    def test_metadata_only_graph_never_downgrades_to_file(self):
        jobs=types.SimpleNamespace(directory='fake',current=None)
        self.state={'current':{'job_id':'a'*32}}
        with patch.object(graph_companion,'read',side_effect=self.read):
            self.assertEqual(self.ns['checked_current'](None,jobs),self.state['current'])
            self.state['current'][graph_companion.KEY]=self.ref
            with self.assertRaises(ValueError):self.ns['checked_current'](None,jobs)

if __name__=='__main__':unittest.main()
