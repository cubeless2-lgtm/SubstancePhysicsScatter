"""Coordinator-only asynchronous Graph UI lane; runpy returns after scheduling.
No nested event loop/processEvents. Only private source/target and a borrowed dock.
"""
from pathlib import Path
import ast,copy,hashlib,json,runpy,sys,time,types,uuid
ROOT=Path('D:/Git/SubstancePhysicsScatter')
BASE=ROOT/'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'
WORK=ROOT/'output/designer_graph_ui'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,value):Path(path).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8'))
def owned(path):
    path=Path(path).resolve()
    if path==WORK.resolve() or not path.is_relative_to(WORK.resolve()):raise ValueError('Outside private Graph UI trial')
    return path
def budget(count,maximum,label):
    if type(count) is not int or not 0<=count<=maximum:raise ValueError(label+' budget')
def load_private(alias,directory,names):
    if alias in sys.modules:raise ValueError('Alias already exists')
    package=types.ModuleType(alias);package.__path__=[str(directory)];package.__package__=alias;sys.modules[alias]=package
    for name in names:
        path=directory/(name+'.py');raw=path.read_bytes();module=types.ModuleType(alias+'.'+name)
        module.__file__=str(path);module.__package__=alias;sys.modules[module.__name__]=module
        exec(compile(raw,str(path),'exec'),module.__dict__);setattr(package,name,module)
    return package

E=dict(status='scheduled',work=str(WORK),product_acceptance=False,original_stock_math_FAIL_preserved=True,native_starts=0,native_attempts=0,inspector=0,capture=0,source_compute=0,source_PNG=0,load_calls=0,new_target_calls=0,target_save_calls=0,final_unload_calls=0,limits=dict(native_children=2,child_seconds=120,combined_log_bytes=4*1024*1024,wall_seconds=360),sdk_root_deleted=False)
dump(REPORT,E) # The file bridge reads this immediately after runpy returns.

class Lane:
    def __init__(self):
        self.started=time.monotonic();self.phase='setup';self.panel=None;self.session=None;self.timer=None;self.before=None;self.before_inventory=None;self.restores=[]
        self.ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0);self.errors=(Exception,);self.finishing=False;self.counter=0;self.logs={}
    def report(self):E.update(phase=self.phase,elapsed_seconds=time.monotonic()-self.started,ledger=copy.deepcopy(self.ledger));dump(REPORT,E)
    def artifact(self,name,value):
        path=owned(WORK/(name+'.json'));dump(path,value);return dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size)
    def saved(self):
        for path,expected in self.spec['saved_files'].items():
            if Path(path).stat().st_size!=expected['size'] or sha(path)!=expected['sha256']:raise ValueError('Protected saved13 changed')
    def user(self,label):
        raw=self.G['protected_snapshot']();self.artifact(label+'-user-raw',raw);self.saved()
        if self.before is not None:
            comparison=self.S['compare'](self.before,raw,self.spec);self.artifact(label+'-user-comparison',comparison)
            if not comparison['semantic_protection_equal']:raise ValueError('User authored state changed')
        return raw
    def setup(self):
        import sd,shiboken6
        from PySide6 import QtCore,QtWidgets
        from sd.api.apiexception import APIException
        self.errors=(Exception,APIException);self.QtCore=QtCore;self.shiboken=shiboken6
        self.app=sd.getContext().getSDApplication();self.manager=self.app.getPackageMgr()
        qapp=QtWidgets.QApplication.instance()
        if qapp is None or QtCore.QThread.currentThread()!=qapp.thread():raise ValueError('SDK UI thread required')
        anchor=qapp.property('substance_physics_scatter_session_v1')
        if anchor is None or not shiboken6.isValid(anchor):raise ValueError('Existing QApplication anchor required; creation0')
        self.state=anchor.scatter_state
        for key in ('dock','layout'):
            if self.state.get(key) is None or not shiboken6.isValid(self.state[key]):raise ValueError('Valid borrowed dock/layout required')
        if self.state.get('panel') is not None or self.state.get('shutdown_process') is not None or self.state.get('failure') or self.state.get('phase')!='hidden' or self.state['layout'].count()!=0:raise ValueError('Existing root is not idle/empty')
        self.dock=self.state['dock'];self.layout=self.state['layout'];self.dock_pointer=shiboken6.getCppPointer(self.dock)[0]
        self.P=runpy.run_path(str(BASE/'ownership.py'));self.F=runpy.run_path(str(BASE/'probe_files.py'));self.G=runpy.run_path(str(BASE/'user_guard.py'));self.S=runpy.run_path(str(BASE/'enum_scope.py'))
        self.spec=self.F['read_json'](BASE/'enum_expected.json');self.before_inventory=self.P['inventory'](self.manager)
        if len(self.before_inventory)!=20 or len(self.spec['saved_files'])!=13:raise ValueError('Expected user20/saved13 baseline')
        self.artifact('inventory-before',self.before_inventory);self.G['configure'](self.manager,self.ledger['owned']);self.before=self.user('before')
        self.product=load_private('_scatter_graph_ui_'+WORK.name,ROOT/'plugin/substance_physics_scatter',('fileio','mask_source','maskio','graph_registry','errors','connections','compat','core','terminal_capture','designer','lifecycle','ui'))
        self.prep=self.F['read_json'](BASE/'preparation.json');self.identities={};self.prepared={};self.disks={}
        for role in ('noise','invert','source'):
            meta=copy.deepcopy(self.prep['packages'][role]);source=BASE/'prepared'/meta['relative_path']
            if sha(source)!=meta['sha256']:raise ValueError('Accepted H2 fixture changed')
            uid=str(uuid.uuid4());raw,proof=self.F['replace_top_uid'](source.read_bytes(),uid);path=owned(WORK/'source'/meta['relative_path']);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            meta.update(uid=uid,sha256=sha(path));self.prepared[role]=meta;self.identities[role]=dict(path=str(path),uid=uid);self.disks[str(path)]=sha(path);self.artifact('uid-'+role,proof)
        for role in ('noise','invert','source'):
            self.artifact('load-'+role,self.P['load_one'](self.manager,role,self.identities[role],self.prepared[role],self.identities,self.ledger,self.before_inventory))
        self.target=self.make_target();self.source_before=[r for r in self.P['states'](self.manager,self.ledger,self.before_inventory)['packages'] if r['role']!='target']
        ui=self.product.ui;lane=self;real_qprocess=QtCore.QProcess
        class CountedProcess(real_qprocess):
            def start(process,executable,args):
                E['native_attempts']+=1;budget(E['native_attempts'],2,'native');request=Path(args[0]);owned(request)
                if sha(executable)!='1c9f16aa6729bd8a4339116aceeada285311541a94cec4ebd25f4ea7c3a98144':raise ValueError('Legacy worker identity differs')
                record=json.loads(request.read_bytes())
                if record['physics_input_format_version']!=2 or record['operation'] not in ('simulate_bake','bake'):raise ValueError('Graph UI fixed input2 operations')
                E['native_starts']+=1;lane.logs[id(process)]=dict(role=lane.phase,bytes=0,request=str(request),request_sha256=sha(request));lane.report()
                QtCore.QTimer.singleShot(120000,lambda:lane.child_timeout(process))
                return super().start(executable,args)
            def readAllStandardOutput(process):
                raw=super().readAllStandardOutput();lane.log(process,'stdout',bytes(raw));return raw
            def readAllStandardError(process):
                raw=super().readAllStandardError();lane.log(process,'stderr',bytes(raw));return raw
        ui.QtCore=types.SimpleNamespace(QProcess=CountedProcess,QTimer=QtCore.QTimer,Qt=QtCore.Qt)
        class TrialPanel(ui.Panel):
            def _refresh(panel):
                graph=lane.product.designer.resolve_scatter(lane.target);panel.nodes.blockSignals(True);panel.nodes.clear();panel.nodes.addItem(graph.getIdentifier(),graph);panel.nodes.blockSignals(False);panel.select()
        class Host(self.product.lifecycle.QtHost):
            def create_dock(host,identifier):raise ValueError('SDK dock creation forbidden')
        self.session=self.product.lifecycle.Session(self.state,Host(TrialPanel,self.app.getQtForPythonUIMgr()))
        self.panel=self.session.initialize();self.panel.enable_graph_ui_for_testing(True)
        g=self.F['read_json'](ROOT/'output/evidence/graph-mask-native-cache-worker-proof/05e92065d78f4c1d91552a19377d10d5/inputs.json')
        self.panel.set_assets(g['assets'])
        for name in ('count','width','depth','seed','seconds'):getattr(self.panel,name).setValue(g['simulation'][name])
        self.panel.edges.setCurrentText('walls');self.panel.resolution.addItem('64');self.panel.resolution.setCurrentText('64');self.panel.normal.setCurrentText('OpenGL');self.panel.height.setValue(8)
        selected=dict(package_path=self.identities['source']['path'],package_uid=self.identities['source']['uid'],graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        self.panel.source_choices.clear();self.panel.source_choices.addItem('PRIVATE NativeMaskSource/native_mask',selected)
        self.install_observers();self.phase='wait_inspection';self.panel.inspect_source();self.report()
    def make_target(self):
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        E['new_target_calls']+=1;budget(E['new_target_calls'],1,'new target');package=self.manager.newUserPackage()
        try:
            identity=self.P['package_id'](package)
            if identity['path'] is not None or any(r['uid']==identity['uid'] for r in self.P['inventory'](self.manager) if r!=identity) or self.P['inventory'](self.manager)!=self.P['order'](self.P['expected'](self.ledger,self.before_inventory)+[identity]):raise ValueError('Unverified fresh target')
            record=dict(name='target',identity=identity,state='adopted');self.ledger['owned'].append(record)
            parent=SDSBSCompGraph.sNew(package);parent.setIdentifier('GraphUITargetParent')
            path=owned(WORK/'target/GraphUITarget.sbs');path.parent.mkdir(parents=True)
            E['target_save_calls']+=1;self.manager.savePackageAs(package,str(path))
            after=self.P['package_id'](package)
            if after!=dict(uid=identity['uid'],path=str(path)):raise ValueError('Target save identity differs')
            record['identity']=after;self.P['context'](self.manager,self.ledger,self.before_inventory);self.disks[str(path)]=sha(path)
            graph,_=self.product.designer.create(parent)
            return self.product.designer.scatter_identity(graph)
        except self.errors:
            self.ledger['ambiguous']=True;raise
    def install_observers(self):
        lane=self;d=self.product.designer;adapter=self.product.terminal_capture
        original_inspect=d.inspect_terminal_selection;original_capture=d.capture_terminal
        self.restores.extend([(d,'inspect_terminal_selection',original_inspect),(d,'capture_terminal',original_capture)])
        O=runpy.run_path(str(BASE/'capture_observer.py'));O['F']['own']=owned
        raw_dir=owned(WORK/'first-capture-raw');raw_dir.mkdir();self.raw_observer=O['Observer'](raw_dir,E,self.artifact);self.raw_observer.calibrate()
        def inspect(*args):
            E['inspector']+=1;budget(E['inspector'],1,'inspector');result=original_inspect(*args);self.artifact('inspection',result);return result
        def capture(*args):
            E['capture']+=1;budget(E['capture'],3,'capture');index=E['capture'];old=adapter._save_texture;expected=Path(args[3])/args[2]/'terminal.png'
            def save(texture,path):
                if index==1:return self.raw_observer.save(old,expected,texture,path)
                old(texture,path)
                if index==2:self.QtCore.QTimer.singleShot(0,self.panel.stop)
                elif index==3:
                    self.session.shutdown()
                    if self.state['panel'] is not self.panel or not self.shiboken.isValid(self.panel):raise ValueError('Disposed inside synchronous capture')
                    E['shutdown_ack_deferred_inside_capture']=True
            adapter._save_texture=save
            try:result=original_capture(*args)
            finally:adapter._save_texture=old
            E['source_compute']+=result['counts']['compute'];E['source_PNG']+=result['counts']['PNG'];self.artifact('capture-'+str(index),result)
            if index==1:self.first_capture=copy.deepcopy(result)
            return result
        d.inspect_terminal_selection=inspect;d.capture_terminal=capture
    def log(self,process,channel,raw):
        if not raw:return
        record=self.logs[id(process)];record['bytes']+=len(raw)
        if record['bytes']>4*1024*1024:process.kill();raise ValueError('Combined native log cap')
        with owned(WORK/(record['role']+'-'+channel+'.log')).open('ab') as stream:stream.write(raw)
    def child_timeout(self,process):
        if self.shiboken.isValid(process) and process.state()!=self.QtCore.QProcess.ProcessState.NotRunning:process.kill();self.fail('Owned native child timeout120s')
    def current(self):
        current=self.panel.jobs.current
        if current is None:raise ValueError('UI handler did not promote a current: '+self.panel.status.text())
        self.product.designer.verify_metadata_current(self.product.designer.resolve_scatter(self.target),self.panel.jobs,current)
        self.product.graph_companion.read(self.panel.jobs.directory,current)
        return current
    def freeze_current(self,current):
        return dict(pointer_sha256=sha(self.panel.jobs.directory/'current.json'),job_id=current['job_id'],poses=current['result']['poses'],origin=current['result']['pose_origin'])
    def assert_same(self):
        now=self.freeze_current(self.current())
        if now!=self.lastgood:raise ValueError('Last-good changed during cancelled/rollback lane')
    def metadata_rollback(self):
        graph=self.product.designer.resolve_scatter(self.target);old=self.product.designer.settings(graph);current=self.current();undo=self.product.designer.update(graph,current,old.get('config'))
        rejected=False
        try:
            changed=self.product.designer.settings(graph);changed['current']['job_id']='0'*32;self.product.designer.store(graph,changed)
            try:self.product.designer.verify_metadata_current(graph,self.panel.jobs,current)
            except self.errors:rejected=True
        finally:undo()
        if not rejected or self.product.designer.settings(graph)!=old:raise ValueError('Metadata rejection/rollback failed')
        E['actual_metadata_rollback_verified']=True;self.assert_same()
    def tick(self):
        if self.finishing:return
        try:
            if self.phase=='failed_wait':
                if self.state['panel'] is not None:return
                if self.state['phase']!='hidden':raise ValueError('Failed shutdown did not acknowledge')
                self.finish(False);return
            if time.monotonic()-self.started>360:raise TimeoutError('Graph UI lane timeout360s')
            if self.phase=='setup':self.setup();return
            if self.phase=='wait_shutdown':
                if self.state['panel'] is not None:return
                if self.state['phase']!='hidden':raise ValueError('Shutdown did not acknowledge')
                E['shutdown_acknowledged']=True;self.finish(True);return
            if self.panel._token is not None or self.panel.process is not None:return
            if self.phase=='wait_inspection':
                if self.panel._source_context is None:raise ValueError('Inspector did not adopt a context: '+self.panel.status.text())
                self.phase='wait_graph';self.panel.run(False)
            elif self.phase=='wait_graph':
                first=self.current();E['first_current']=self.artifact('first-current',first)
                mask=first['request']['scatter_mask'];png=self.first_capture['png']
                if sha(mask['path'])!=png['sha256']:raise ValueError('Capture/cache bytes differ')
                E['capture_cache_exact']=True;self.first=copy.deepcopy(first);self.phase='wait_saved';self.panel.run(True)
            elif self.phase=='wait_saved':
                saved=self.current()
                if saved['job_id']==self.first['job_id'] or saved['result']['execution']!={'physics_executed':False,'body_count':0,'steps':0} or saved['result']['poses']!=self.first['result']['poses'] or saved['result']['pose_origin']!=self.first['result']['pose_origin']:raise ValueError('Saved physics/origin differs')
                E['saved_current']=self.artifact('saved-current',saved);self.lastgood=self.freeze_current(saved);self.metadata_rollback()
                try:
                    saved=self.panel.grab().save(str(owned(WORK/'graph-ui.png')));E['widget_capture']={'path':str(WORK/'graph-ui.png'),'save_returned':bool(saved),'exists':(WORK/'graph-ui.png').is_file()}
                except self.errors as error:E['widget_capture']={'error':str(error)}
                self.phase='wait_cancel';self.panel.run(False)
            elif self.phase=='wait_cancel':
                self.assert_same()
                if E['native_attempts']!=2:raise ValueError('Queued cancel reached worker start')
                E['queued_cancel_worker0']=True;self.phase='wait_shutdown';self.panel.run(False)
            self.report()
        except self.errors as error:
            message=type(error).__name__+': '+str(error);error.__traceback__=None;error.__cause__=None;error.__context__=None
            self.fail(message)
    def fail(self,message):
        E.update(status='failed',error=message)
        if self.panel is not None and self.shiboken.isValid(self.panel) and (self.panel._token is not None or self.panel.process is not None):
            self.session.shutdown();self.phase='failed_wait';self.report();return
        self.finish(False)
    def finish(self,success):
        if self.finishing:return
        self.finishing=True
        try:
            if self.panel is not None and self.shiboken.isValid(self.panel):
                if self.panel._token is not None or self.panel.process is not None:raise ValueError('Cannot dispose while operation remains')
                self.session.shutdown()
            for obj,name,value in reversed(self.restores):setattr(obj,name,value)
            if self.before_inventory is not None:
                source_equal=True
                if not self.ledger['ambiguous'] and hasattr(self,'source_before'):
                    source_equal=[r for r in self.P['states'](self.manager,self.ledger,self.before_inventory)['packages'] if r['role']!='target']==self.source_before
                E['private_source_state_unchanged']=source_equal
                E['cleanup']=self.P['cleanup'](self.manager,self.ledger,self.before_inventory,self.errors)
                final=self.P['inventory'](self.manager);self.artifact('inventory-final',final);self.saved()
                E['final_user_guard']=self.P['finish_guard'](self.ledger,final,self.before_inventory,self.before is not None,lambda:self.user('final'))
                if not E['final_user_guard']['verified']:raise ValueError('User protection unverified; safe inventory/saved13 only')
                if not source_equal:raise ValueError('Private source/stock state changed')
                if any(sha(p)!=h for p,h in self.disks.items()):raise ValueError('Private disk changed')
                if not self.shiboken.isValid(self.dock) or self.shiboken.getCppPointer(self.dock)[0]!=self.dock_pointer or self.state['dock'] is not self.dock or self.state['layout'] is not self.layout or self.layout.count()!=0:raise ValueError('Borrowed native root changed')
                E['dock_root_unchanged']=True
            E['status']='PASS_LIMITED_GRAPH_UI' if success else 'failed'
        except self.errors as error:E.update(status='failed',cleanup_error=str(error))
        finally:
            E['native_records']=list(self.logs.values());E['final_unload_calls']=self.ledger['final_unload_calls'];self.report()
            if self.timer is not None:self.timer.stop();self.timer.deleteLater()

def schedule():
    from PySide6 import QtCore,QtWidgets
    lane=Lane();lane.timer=QtCore.QTimer(QtWidgets.QApplication.instance());lane.timer.setInterval(50);lane.timer.timeout.connect(lane.tick);lane.timer.start()
    return lane

if __name__=='__main__':
    try:LANE=schedule()
    except Exception as error:E.update(status='failed_schedule',error=str(error));dump(REPORT,E)
