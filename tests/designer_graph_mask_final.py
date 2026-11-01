"""Root-only canonical Graph UI integration; separate, never-shown own container.

Three real children: Sim64, Saved128, reopened/source-absent Saved64. No UI input,
screenshots, native dock creation, canonical registry mutation or module reload.
"""
from pathlib import Path
import ast,copy,hashlib,json,runpy,time,types,uuid,traceback

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'
LEGACY=ROOT/'tests/designer_graph_ui_actual.py'
WORK=None
REPORT=None
E={}
WORKER_SHA='1c9f16aa6729bd8a4339116aceeada285311541a94cec4ebd25f4ea7c3a98144'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned(path):
    router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'))
    path=router['owned'](ROOT,path)
    if WORK is None or path==WORK or not path.is_relative_to(WORK):raise ValueError('Outside own Graph final work')
    return path


def dump(path,value):
    Path(path).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8'))


def restore_held_files(journal,own,publish):
    """Each moved file is restored once, in reverse order; never overwrite."""
    failures=[]
    for row in reversed(journal['files']):
        original=own(row['original']);held=own(row['hold'])
        try:
            if original.parent!=held.parent or original.suffix.lower()!='.sbs' or not held.name.startswith(original.name+'.hold-'):raise ValueError('Restore original/hold boundary differs')
            if row['state']=='restore_failed':raise ValueError('Earlier file restoration failed; no automatic retry')
            if original.exists():
                if held.exists() or sha(original)!=row['sha256']:raise ValueError('Original path conflict or original SHA differs')
                row['state']='restored';publish(journal);continue
            if not held.is_file() or sha(held)!=row['sha256']:raise ValueError('Held source absent or SHA differs')
            row['state']='restoring';publish(journal)
            held.rename(original)
            if held.exists() or sha(original)!=row['sha256']:raise ValueError('Source restore SHA/path differs')
            row['state']='restored';publish(journal)
        except Exception as error:
            row.update(state='restore_failed',error=type(error).__name__+': '+str(error));failures.append(row['original']);publish(journal)
    journal['status']='restore_failed' if failures else 'restored';publish(journal)
    if failures:raise RuntimeError('Owned source file restoration failed; inspect journal, no overwrite/retry: '+', '.join(failures))


def hold_source_files(journal,own,publish):
    """Hold exactly three unloaded own SBS files, with a write-ahead journal."""
    rows=journal['files']
    if len(rows)!=3 or [r['role'] for r in rows]!=['noise','invert','source'] or len({r['original'] for r in rows})!=3 or len({r['hold'] for r in rows})!=3:raise ValueError('Exact three distinct source/hold files required')
    for row in rows:
        original=own(row['original']);held=own(row['hold'])
        if (original.parent!=held.parent or original.suffix.lower()!='.sbs' or not held.name.startswith(original.name+'.hold-')
                or not original.is_file() or held.exists() or sha(original)!=row['sha256']):raise ValueError('Invalid own source file/hold boundary or SHA')
        row['state']='planned'
    journal['status']='planned';publish(journal) # All intended paths before any move.
    try:
        for row in rows:
            original=own(row['original']);held=own(row['hold'])
            if held.exists() or sha(original)!=row['sha256']:raise ValueError('Source changed before file hold')
            row['state']='moving';publish(journal)
            original.rename(held)
            if original.exists() or sha(held)!=row['sha256']:raise ValueError('Held file SHA/path differs')
            row['state']='held';publish(journal)
        journal['status']='held';publish(journal)
    except Exception:
        journal['status']='hold_failed';journal['rollback_attempted']=True;publish(journal)
        restore_held_files(journal,own,publish)
        raise


def clear_panel_wrappers(panel):
    """Before any package unload, release SDK graph itemData and cached context."""
    if panel._token is not None or panel.process is not None:raise ValueError('Cannot unload while own operation is pending')
    panel.invalidate_source();panel.graph=None;panel._target_identity=None;panel.jobs=None
    for combo in (panel.nodes,panel.source_choices):
        combo.blockSignals(True)
        try:combo.clear()
        finally:combo.blockSignals(False)


def require_saved(original,saved,resolution):
    if saved['job_id']==original['job_id'] or saved['request']['bake']['resolution']!=resolution:raise ValueError('Saved identity/resolution differs')
    if (saved['result']['execution']!=dict(physics_executed=False,body_count=0,steps=0)
            or saved['result']['poses']!=original['result']['poses']
            or saved['result']['pose_origin']!=original['result']['pose_origin']):raise ValueError('Saved physics/poses/origin differs')


def require_maps_exact(first,second):
    result={name:dict(first_sha256=sha(first['files'][name]),second_sha256=sha(second['files'][name])) for name in ('height','normal','coverage')}
    if any(row['first_sha256']!=row['second_sha256'] for row in result.values()):raise ValueError('Restored64 maps differ at byte-exact0')
    return result


def verified_checks():
    """Reuse only these previously exercised checks, not the old runner startup."""
    tree=ast.parse(LEGACY.read_text(encoding='utf8'))
    klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Lane')
    wanted=('current','freeze_current','assert_same','metadata_rollback')
    methods=[next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name==name) for name in wanted]
    node=ast.ClassDef(name='VerifiedChecks',bases=[],keywords=[],body=methods,decorator_list=[])
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    namespace=dict(E=E,sha=sha,copy=copy)
    exec(compile(module,str(LEGACY),'exec'),namespace)
    return namespace['VerifiedChecks']


class Lane(verified_checks()):
    def __init__(self):
        self.started=time.monotonic();self.phase='setup';self.finishing=False;self.panel=None;self.timer=None
        self.session=None;self.container=None;self.manager=None;self.before=None;self.before_inventory=None
        self.errors=(Exception,);self.logs={};self.disks={};self.held=False;self.target=None;self.hold_journal=None
        self.ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0,reopen_unload_calls=0,source_absence_unload_calls=0)
    def artifact(self,name,value):
        path=owned(WORK/(name+'.json'))
        with path.open('x',encoding='utf8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        return dict(path=str(path),sha256=sha(path),bytes=path.stat().st_size)
    def report(self):
        E.update(phase=self.phase,elapsed_seconds=time.monotonic()-self.started,ledger=copy.deepcopy(self.ledger))
        temporary=owned(WORK/'report.tmp');dump(temporary,E);temporary.replace(REPORT)
    def hold_record(self,journal):
        path=owned(WORK/'source-file-hold-journal.json');temporary=owned(WORK/'source-file-hold-journal.tmp')
        dump(temporary,journal);temporary.replace(path)
        E['source_file_hold_journal']=copy.deepcopy(journal);self.report()
    def saved(self):
        if len(self.spec['saved_files'])!=13:raise ValueError('Exact saved13 protection required')
        for path,expected in self.spec['saved_files'].items():
            if Path(path).stat().st_size!=expected['size'] or sha(path)!=expected['sha256']:raise ValueError('Protected saved13 changed')
    def user(self,label):
        raw=self.G['protected_snapshot']();self.artifact(label+'-user-raw',raw);self.saved()
        if self.before is not None:
            comparison=self.S['compare'](self.before,raw,self.spec);self.artifact(label+'-user-comparison',comparison)
            if not comparison['semantic_protection_equal']:raise ValueError('User authored state changed')
        return raw
    def affinity(self,label):
        value=self.product.evaluation._ProcessAffinity().get()
        E.setdefault('affinity',[]).append(dict(stage=label,mask=value))
        if value!=65535:raise ValueError('Expected restored affinity65535 at '+label)
    def source_states(self):
        return [r for r in self.P['states'](self.manager,self.ledger,self.before_inventory)['packages'] if r['role']!='target']
    def setup(self):
        import sd,shiboken6,substance_physics_scatter
        from PySide6 import QtCore,QtWidgets
        from sd.api.apiexception import APIException
        from substance_physics_scatter import ui,designer,lifecycle,terminal_capture,evaluation,graph_companion
        from substance_physics_scatter.ui_observation import current
        self.errors=(Exception,APIException);self.QtCore=QtCore;self.shiboken=shiboken6;self.product=substance_physics_scatter
        self.app=sd.getContext().getSDApplication();self.manager=self.app.getPackageMgr()
        self.qapp=QtWidgets.QApplication.instance()
        evaluation._assert_environment();self.affinity('setup')
        self.user_ui_before=current();self.artifact('canonical-ui-before',self.user_ui_before)
        panel=self.user_ui_before.get('panel',{})
        if (self.user_ui_before.get('status')!='observed' or panel.get('operation_contract_available') is not True
                or panel.get('operation_pending') is not False or panel.get('operation_phase')!='idle'
                or panel.get('closing') is not False or panel.get('lifecycle_stopping') is not False
                or any(self.user_ui_before.get(key,{}).get('present') is not False for key in ('process','shutdown_process'))):raise ValueError('Canonical user UI must remain idle and observed')
        if designer.compute_graph is not evaluation.compute_graph or 'evaluation_scope' not in terminal_capture.capture_terminal.__code__.co_names:raise ValueError('Current transaction evaluation code not loaded')
        self.canonical_current=current;self.ui=ui
        self.P=runpy.run_path(str(BASE/'ownership.py'));self.F=runpy.run_path(str(BASE/'probe_files.py'))
        self.G=runpy.run_path(str(BASE/'user_guard.py'));self.S=runpy.run_path(str(BASE/'enum_scope.py'))
        self.O=runpy.run_path(str(BASE/'capture_observer.py'));self.O['F']['own']=owned
        self.C=runpy.run_path(str(BASE/'caller.py'));self.spec=self.F['read_json'](BASE/'enum_expected.json')
        self.prep=self.F['read_json'](BASE/'preparation.json');self.identities={};self.prepared={}
        self.before_inventory=self.P['inventory'](self.manager)
        if len(self.before_inventory)!=20:raise ValueError('Expected original user20')
        self.artifact('inventory-before',self.before_inventory);self.G['configure'](self.manager,self.ledger['owned']);self.before=self.user('before')
        for role in ('noise','invert','source'):
            meta=copy.deepcopy(self.prep['packages'][role]);path=BASE/'prepared'/meta['relative_path']
            if sha(path)!=meta['sha256']:raise ValueError('Accepted preparation changed')
            uid=str(uuid.uuid4());raw,proof=self.F['replace_top_uid'](path.read_bytes(),uid)
            target=owned(WORK/'source'/meta['relative_path']);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
            meta.update(uid=uid,sha256=sha(target));self.prepared[role]=meta;self.identities[role]=dict(path=str(target),uid=uid)
            self.disks[str(target)]=sha(target);self.artifact('uid-'+role,proof)
        for role in ('noise','invert','source'):
            self.artifact('load-'+role,self.P['load_one'](self.manager,role,self.identities[role],self.prepared[role],self.identities,self.ledger,self.before_inventory))
        self.source_before=self.source_states();self.target=self.make_target()
        lane=self;real_process=QtCore.QProcess
        class CountedProcess(real_process):
            def start(process,executable,args):
                E['native_attempts']+=1
                if E['native_attempts']>3:raise ValueError('Native3 maximum')
                if len(args)!=1 or sha(executable)!=WORKER_SHA:raise ValueError('Fixed legacy worker/argument differs')
                request=owned(Path(args[0]));document=json.loads(request.read_bytes())
                wanted=(('simulate_bake',64),('bake',128),('bake',64))[E['native_attempts']-1]
                if (document['operation'],document['bake']['resolution'])!=wanted or document['physics_input_format_version']!=2:raise ValueError('Fixed Sim64/Saved128/Saved64 input2 sequence differs')
                lane.logs[id(process)]=dict(phase=lane.phase,bytes=0,request=str(request),sha256=sha(request));E['native_starts']+=1;lane.report()
                QtCore.QTimer.singleShot(120000,lambda:lane.child_timeout(process))
                return super().start(executable,args)
            def readAllStandardOutput(process):
                raw=super().readAllStandardOutput();lane.log(process,'stdout',bytes(raw));return raw
            def readAllStandardError(process):
                raw=super().readAllStandardError();lane.log(process,'stderr',bytes(raw));return raw
        class TrialPanel(ui.Panel):
            def _refresh(panel):
                graph=designer.resolve_scatter(lane.target);panel.nodes.blockSignals(True)
                try:panel.nodes.clear();panel.nodes.addItem(graph.getIdentifier(),graph)
                finally:panel.nodes.blockSignals(False)
                panel.select()
            def inspect_source(panel):return lane.sync_inspect(super().inspect_source)
            def run(panel,rebake):return lane.sync_run(panel,rebake,super().run)
            def _prepare_and_start(panel,*args):
                previous=ui.QtCore;ui.QtCore=types.SimpleNamespace(QProcess=CountedProcess,QTimer=QtCore.QTimer,Qt=QtCore.Qt)
                try:return super()._prepare_and_start(*args)
                finally:ui.QtCore=previous
        class OwnHost(lifecycle.QtHost):
            def create_dock(host,identifier):raise ValueError('Native dock creation forbidden')
            def show(host,widget):pass  # No OS window display or screenshot.
            def hide(host,widget):pass
        self.container=QtWidgets.QWidget();layout=QtWidgets.QVBoxLayout(self.container)
        self.state=dict(version=1,dock=self.container,layout=layout,layout_version=1,generation=0,phase='hidden',failure=None,native_attempted=True,panel=None,shutdown_process=None)
        self.session=lifecycle.Session(self.state,OwnHost(TrialPanel,None));self.panel=self.session.initialize()
        g=self.F['read_json'](ROOT/'output/evidence/graph-mask-native-cache-worker-proof/05e92065d78f4c1d91552a19377d10d5/inputs.json')
        self.panel.set_assets(g['assets'])
        for key in ('count','width','depth','seed','seconds'):getattr(self.panel,key).setValue(g['simulation'][key])
        self.panel.edges.setCurrentText('walls');self.panel.resolution.addItems(['64','128']);self.panel.resolution.setCurrentText('64');self.panel.normal.setCurrentText('OpenGL');self.panel.height.setValue(8)
        self.choose_source();self.phase='wait_inspection';self.panel.inspect_source();self.report()
    def make_target(self):
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        E['new_target']+=1
        try:
            package=self.manager.newUserPackage()
            identity=self.P['package_id'](package)
            if identity['path'] is not None or any(r['uid']==identity['uid'] for r in self.P['expected'](self.ledger,self.before_inventory)) or self.P['inventory'](self.manager)!=self.P['order'](self.P['expected'](self.ledger,self.before_inventory)+[identity]):raise ValueError('New target identity/inventory ambiguous')
            record=dict(name='target',identity=identity,state='adopted');self.ledger['owned'].append(record)
            parent=SDSBSCompGraph.sNew(package);parent.setIdentifier('GraphFinalParent')
            path=owned(WORK/'target/GraphFinal.sbs');path.parent.mkdir()
            E['target_saves']+=1;self.manager.savePackageAs(package,str(path))
            after=self.P['package_id'](package)
            if after!=dict(uid=identity['uid'],path=str(path)):raise ValueError('Target save identity differs')
            record['identity']=after;self.P['context'](self.manager,self.ledger,self.before_inventory);self.disks[str(path)]=sha(path)
            graph,_=self.product.designer.create(parent)
            return self.product.designer.scatter_identity(graph)
        except self.errors:self.P['ambiguous'](self.ledger,'Unknown target creation/save identity');raise
    def choose_source(self):
        value=dict(package_path=self.identities['source']['path'],package_uid=self.identities['source']['uid'],graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        self.panel.source_choices.clear();self.panel.source_choices.addItem('OWN NativeMaskSource/native_mask',value)
    def sync_inspect(self,call):
        d=self.product.designer;original=d.inspect_terminal_selection
        def observe(*args):
            E['inspector']+=1
            if E['inspector']>2:raise ValueError('Inspector2 maximum')
            result=original(*args);self.last_inspection=copy.deepcopy(result);self.artifact('inspection-'+str(E['inspector']),result);self.affinity('after-inspector-'+str(E['inspector']));return result
        d.inspect_terminal_selection=observe
        try:return call()
        finally:d.inspect_terminal_selection=original
    def sync_run(self,panel,rebake,call):
        d=self.product.designer;adapter=self.product.terminal_capture;original=d.capture_terminal
        def observe(*args):
            E['capture']+=1;index=E['capture']
            if index>2:raise ValueError('Capture2 maximum')
            row={};E.setdefault('capture_observers',[]).append(row)
            directory=owned(WORK/('raw-'+str(index)));directory.mkdir();observer=self.O['Observer'](directory,row,lambda n,v:self.artifact(n+'-'+str(index),v));observer.calibrate()
            expected=Path(args[3])/args[2]/'terminal.png';old=adapter._save_texture
            adapter._save_texture=lambda texture,path:observer.save(old,expected,texture,path)
            try:
                result=original(*args);observer.record_counts(result,'returned');self.artifact('capture-'+str(index),result)
            except adapter.CaptureError as error:
                observer.record_counts(error.record,'CaptureError');self.artifact('capture-failure-'+str(index),error.record);raise
            finally:adapter._save_texture=old;row['hook_restored']=adapter._save_texture is old
            values=dict(selection=args[0],selected_context=args[1],operation_id=args[2],owned_directory=args[3],forbidden_bitmap_paths=args[4])
            row['verification']=self.O['verify'](result,values,self.last_inspection,self.product.mask_source,observer)
            self.affinity('after-capture-'+str(index))
            if index==1:self.first_capture=copy.deepcopy(result)
            if self.phase=='wait_cancel':self.QtCore.QTimer.singleShot(0,panel.stop)
            return result
        d.capture_terminal=observe
        try:return call(rebake)
        finally:d.capture_terminal=original
    def log(self,process,channel,raw):
        if not raw:return
        row=self.logs[id(process)];row['bytes']+=len(raw)
        if sum(r['bytes'] for r in self.logs.values())>4*1024*1024:process.kill();raise ValueError('Combined own child log4MiB cap')
        with owned(WORK/(row['phase']+'-'+channel+'.log')).open('ab') as stream:stream.write(raw)
    def child_timeout(self,process):
        if not self.finishing and id(process) in self.logs and self.shiboken.isValid(process) and process.state()!=self.QtCore.QProcess.ProcessState.NotRunning:process.kill();self.fail('Own child120s timeout')
    def target_record(self):
        rows=[r for r in self.P['active'](self.ledger) if r['name']=='target']
        if len(rows)!=1:self.P['ambiguous'](self.ledger,'Target ledger is not unique');raise ValueError('Target ledger ambiguous')
        return rows[0]
    def save_target(self):
        try:
            record=self.target_record();package=self.P['canonical'](self.manager,record,self.ledger,self.before_inventory)
            E['target_saves']+=1;self.manager.savePackage(package)
            if self.P['package_id'](package)!=record['identity']:raise ValueError('Target identity changed')
            self.disks[record['identity']['path']]=sha(record['identity']['path'])
        except self.errors:self.P['ambiguous'](self.ledger,'Target save result/identity unverified');raise
    def reload_target(self,identity,graph_identifier,metadata):
        self.P['context'](self.manager,self.ledger,self.before_inventory);E['target_reload']+=1
        try:
            if E['target_reload']!=1:raise ValueError('Target reload once only')
            package=self.manager.loadUserPackage(identity['path'],False,False)
            if package is None or self.P['package_id'](package)!=identity or self.P['inventory'](self.manager)!=self.P['order'](self.P['expected'](self.ledger,self.before_inventory)+[identity]):raise ValueError('Unadopted target reload')
            graphs=[g for g in package.getChildrenResources(False) if isinstance(g,self.product.designer.SDSBSCompGraph) and g.getIdentifier()==graph_identifier]
            if len(graphs)!=1 or self.product.designer.settings(graphs[0])!=metadata:raise ValueError('Target graph/metadata reload differs')
            fresh=self.product.designer.scatter_identity(graphs[0])
            self.ledger['owned'].append(dict(name='target',identity=copy.deepcopy(identity),state='adopted'))
            self.P['context'](self.manager,self.ledger,self.before_inventory)
            return fresh
        except self.errors:self.P['ambiguous'](self.ledger,'Unknown target reload identity; no related cleanup/full user reader');raise
    def source_absence(self):
        self.affinity('before-reopen')
        if self.source_states()!=self.source_before:raise ValueError('Source state changed before planned unload')
        graph=self.product.designer.resolve_scatter(self.target);metadata=copy.deepcopy(self.product.designer.settings(graph));graph=None
        self.save_target();record=self.target_record();identity=copy.deepcopy(record['identity']);graph_id=self.target['graph_identifier']
        clear_panel_wrappers(self.panel)
        self.artifact('target-prep-unload',self.P['remove'](self.manager,record,self.ledger,self.before_inventory,'reopen'))
        self.target=self.reload_target(identity,graph_id,metadata);self.panel.refresh()
        if self.panel.graph is None or self.current()['job_id']!=self.saved128['job_id']:raise ValueError('Saved target did not reopen')
        for record in list(reversed(self.P['active'](self.ledger))):
            if record['name']!='target':self.artifact('source-unload-'+record['name'],self.P['remove'](self.manager,record,self.ledger,self.before_inventory,'source_absence'))
        self.phase='wait_source_hold' # File moves happen on the next existing Qt timer tick.
        E['source_unload_completed_before_hold']=True
    def hold_source(self):
        self.P['context'](self.manager,self.ledger,self.before_inventory)
        if any(row['uid'] in {i['uid'] for i in self.identities.values()} for row in self.P['inventory'](self.manager)):raise ValueError('Source UID still loaded before file hold')
        rows=[]
        for role in ('noise','invert','source'):
            path=owned(self.identities[role]['path']);hold=owned(path.with_name(path.name+'.hold-'+uuid.uuid4().hex))
            rows.append(dict(role=role,original=str(path),hold=str(hold),sha256=self.disks[str(path)],state='planned'))
        self.hold_journal=dict(version=1,status='preparing',rollback_attempted=False,files=rows)
        self.held=True # The helper itself rolls partial success back before raising.
        try:hold_source_files(self.hold_journal,owned,self.hold_record)
        finally:self.held=any(r['state']!='restored' for r in rows) and self.hold_journal['status']!='preparing'
        E['source_absence']=dict(paths=[r['path'] for r in self.identities.values()],all_absent=all(not Path(r['path']).exists() for r in self.identities.values()),loaded_private_sources=0)
        if not E['source_absence']['all_absent']:raise ValueError('Source paths remain present')
        self.panel.resolution.setCurrentText('64');self.phase='wait_saved64';self.panel.run(True)
    def restore_source(self,load=True):
        if self.held:
            restore_held_files(self.hold_journal,owned,self.hold_record)
            self.held=False;E['source_files_restored']=True
        if not load:return
        phase=dict(owned=self.ledger['owned'],ambiguous=self.ledger['ambiguous'],load_calls=0,final_unload_calls=0)
        try:
            for role in ('noise','invert','source'):
                self.artifact('source-reload-'+role,self.P['load_one'](self.manager,role,self.identities[role],self.prepared[role],self.identities,phase,self.before_inventory))
        finally:
            E['source_restore_loads']=phase['load_calls']
            if phase['ambiguous']:self.P['ambiguous'](self.ledger,phase.get('ambiguity_reason','Source restore ownership ambiguous'))
        if self.source_states()!=self.source_before:raise ValueError('Restored source state differs')
    def tick(self):
        if self.finishing:return
        try:
            if time.monotonic()-self.started>360:raise TimeoutError('Graph final wall360s')
            if self.phase=='setup':self.setup();return
            if self.phase in ('wait_cleanup','failed_wait'):
                if self.state.get('panel') is not None:return
                self.finish(self.phase=='wait_cleanup');return
            if self.panel._token is not None or self.panel.process is not None:return
            self.affinity(self.phase)
            if self.phase=='wait_inspection':
                if self.panel._source_context is None:raise ValueError('Source inspection failed: '+self.panel.status.text())
                self.phase='wait_sim64';self.panel.run(False)
            elif self.phase=='wait_sim64':
                first=self.current();self.first=copy.deepcopy(first);self.artifact('sim64-current',first)
                if first['request']['bake']['resolution']!=64 or sha(first['request']['scatter_mask']['path'])!=self.first_capture['png']['sha256']:raise ValueError('Sim64 capture/cache mismatch')
                self.panel.resolution.setCurrentText('128');self.phase='wait_saved128';self.panel.run(True)
            elif self.phase=='wait_saved128':
                self.saved128=copy.deepcopy(self.current());require_saved(self.first,self.saved128,128);self.artifact('saved128-current',self.saved128);self.source_absence()
            elif self.phase=='wait_source_hold':self.hold_source()
            elif self.phase=='wait_saved64':
                saved=self.current();require_saved(self.first,saved,64);E['source_absent_saved64_maps']=require_maps_exact(self.first,saved)
                self.artifact('source-absent-saved64-current',saved);self.lastgood=self.freeze_current(saved)
                self.restore_source();self.choose_source();self.phase='wait_fresh_inspection';self.panel.inspect_source()
            elif self.phase=='wait_fresh_inspection':
                if self.panel._source_context is None:raise ValueError('Fresh inspection after reload failed')
                self.phase='wait_cancel';self.panel.run(False)
            elif self.phase=='wait_cancel':
                self.assert_same()
                if E['native_attempts']!=3:raise ValueError('Queued cancel started a worker')
                E['queued_cancel_worker0']=True;self.metadata_rollback();self.assert_same();self.affinity('after-metadata-rollback')
                self.phase='wait_cleanup';self.session.shutdown()
            self.report()
        except self.errors as error:
            message=type(error).__name__+': '+str(error);E['error_traceback']=traceback.format_exc()
            error.__traceback__=None;error.__cause__=None;error.__context__=None;self.fail(message)
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
                clear_panel_wrappers(self.panel);self.session.shutdown()
            if self.held:
                try:self.restore_source(load=False) # Files only; never retry an SDK load.
                except self.errors as error:
                    success=False;E['source_file_restore_error']=type(error).__name__+': '+str(error)
                    error.__traceback__=None;error.__cause__=None;error.__context__=None
            if self.before_inventory is not None:
                E['source_state_unchanged']=False
                if not self.ledger['ambiguous'] and hasattr(self,'source_before'):
                    try:
                        E['source_state_unchanged']=self.source_states()==self.source_before
                        if not E['source_state_unchanged']:success=False
                    except self.errors as error:
                        success=False;E['source_state_error']=type(error).__name__+': '+str(error)
                        error.__traceback__=None;error.__cause__=None;error.__context__=None
                E['cleanup']=self.P['cleanup'](self.manager,self.ledger,self.before_inventory,self.errors)
                final=self.P['inventory'](self.manager);self.artifact('inventory-final',final);self.saved()
                E['final_user_guard']=self.P['finish_guard'](self.ledger,final,self.before_inventory,self.before is not None,lambda:self.user('final'))
                if not E['final_user_guard']['verified']:raise ValueError('Full user guard unverified; safe inventory/saved13 only')
                if any(sha(path)!=digest for path,digest in self.disks.items()):raise ValueError('Owned original disks changed')
            if hasattr(self,'canonical_current'):
                after=self.canonical_current();self.artifact('canonical-ui-after',after)
                if after!=self.user_ui_before:raise ValueError('Canonical user panel/dock/registry changed')
                E['canonical_ui_unchanged']=True;self.affinity('final')
            E['status']='PASS_LIMITED_CANONICAL_GRAPH_FLOW' if success else 'failed'
        except self.errors as error:
            E.update(status='failed',cleanup_error=type(error).__name__+': '+str(error));error.__traceback__=None;error.__cause__=None;error.__context__=None
        finally:
            if self.container is not None and self.shiboken.isValid(self.container) and self.state.get('panel') is None:self.container.deleteLater()
            E['native_records']=list(self.logs.values());self.report()
            if self.timer is not None:self.timer.stop();self.timer.deleteLater()


def schedule():
    global WORK,REPORT
    from PySide6 import QtCore,QtWidgets
    router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));router['project_root']()
    WORK=router['owned'](ROOT,ROOT/'output/designer_bridge/graph-mask-final'/uuid.uuid4().hex);WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
    E.update(status='scheduled',work=str(WORK),native_attempts=0,native_starts=0,inspector=0,capture=0,new_target=0,target_saves=0,target_reload=0,
             product_acceptance=False,original_failures_preserved=True,computer_use=False,screenshots=0,tolerance=0,
             limits=dict(native_children=3,child_seconds=120,combined_log_bytes=4194304,wall_seconds=360,source_loads=6,target_reload=1,new_package=1,target_saves=2,total_unload_max=8))
    dump(REPORT,E)
    lane=Lane();lane.timer=QtCore.QTimer(QtWidgets.QApplication.instance());lane.timer.setInterval(50);lane.timer.timeout.connect(lane.tick);lane.timer.start();return lane


if __name__=='__main__':LANE=schedule()
