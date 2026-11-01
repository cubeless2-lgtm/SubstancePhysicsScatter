"""Root-run user example preparation; retains its four packages on success.

Uses the existing canonical idle Panel, one real legacy worker and no computer
use, widget replacement, screenshot, module reload or existing package edits.
"""
from pathlib import Path
import copy,hashlib,json,runpy,time,types,uuid,traceback

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'
LIBRARY=Path('D:/Git/Hunyuan3D-2.1/outputs/scatter_review_20261031/asset_library.json')
BRICK=LIBRARY.parent/'brick_red/final_clean/brick_red.obj'
BRICK_SHA='e96fe43423cd6a436bbab243509a376051a6adb04ecd8872708c75a650aa30ae'
WORKER_SHA='1c9f16aa6729bd8a4339116aceeada285311541a94cec4ebd25f4ea7c3a98144'
WORK=None
REPORT=None
E={}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def own(path):
    router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));path=router['owned'](ROOT,path)
    if WORK is None or path==WORK or not path.is_relative_to(WORK):raise ValueError('Outside own review example')
    return path


def brick_asset(library,source):
    document=json.loads(Path(library).read_text(encoding='utf8'))
    matches=[r for r in document['assets'] if r['asset_id']=='brick_red']
    if len(matches)!=1:raise ValueError('Unique brick_red library entry required')
    row=matches[0];meta=row['files']['obj'];source=Path(source)
    if Path(meta['path']).resolve()!=source.resolve() or meta['sha256']!=BRICK_SHA or source.stat().st_size!=meta['bytes']:raise ValueError('Fixed original brick locator/hash differs')
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=BRICK_SHA:raise ValueError('Original brick bytes differ')
    faces=[line.split() for line in raw.splitlines() if line.split()[:1]==[b'f']]
    if row['triangle_count']!=4998 or len(faces)!=4998 or any(len(face)!=4 for face in faces):raise ValueError('Fixed brick must be4998 triangles, below5000')
    if row['units']!='meters' or row['up_axis']!='Z':raise ValueError('Fixed brick coordinate basis differs')
    return raw,dict(source=str(source),sha256=BRICK_SHA,triangles=4998,dimensions_m=row['dimensions_m'],geometry_only=True)


def panel_snapshot(panel):
    result=dict(target=copy.deepcopy(panel._target_identity),assets=copy.deepcopy(panel.asset_rows()),mask=copy.deepcopy(panel.mask_config()),
        simulation={key:getattr(panel,key).value() for key in ('count','width','depth','seed','seconds')},
        edges=panel.edges.currentText(),resolution=panel.resolution.currentText(),normal=panel.normal.currentText(),height=panel.height.value(),
        mask_mode=panel.mask_mode.currentText(),source_items=[dict(label=panel.source_choices.itemText(i),value=copy.deepcopy(panel.source_choices.itemData(i))) for i in range(panel.source_choices.count())],
        source_index=panel.source_choices.currentIndex())
    if panel.jobs is not None:
        path=Path(panel.jobs.directory)/'current.json'
        if path.is_file():result['previous_current']=dict(path=str(path),sha256=sha(path))
    json.dumps(result,allow_nan=False) # No SDK wrapper may enter the snapshot.
    return result


class Prepare:
    def __init__(self):
        self.started=time.monotonic();self.phase='setup';self.timer=None;self.panel=None;self.manager=None;self.before=None;self.inventory_before=None
        self.errors=(Exception,);self.target=None;self.disks={};self.processes={};self.finishing=False;self.snapshot=None
        self.original_prepare=None;self.previous_prepare=None;self.had_prepare=False;self.owned_tokens=set()
        self.panel_modified=False;self.after_guard_attempted=False;self.after_guard_verified=False
        self.ledger=dict(owned=[],ambiguous=False,load_calls=0,final_unload_calls=0)
    def artifact(self,name,value):
        path=own(WORK/(name+'.json'))
        with path.open('x',encoding='utf8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        return dict(path=str(path),sha256=sha(path))
    def report(self):
        E.update(phase=self.phase,elapsed_seconds=time.monotonic()-self.started,ledger=copy.deepcopy(self.ledger))
        path=own(WORK/'report.tmp');path.write_bytes((json.dumps(E,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf8'));path.replace(REPORT)
    def saved(self):
        if len(self.spec['saved_files'])!=13:raise ValueError('Exact saved13 guard required')
        for path,meta in self.spec['saved_files'].items():
            if Path(path).stat().st_size!=meta['size'] or sha(path)!=meta['sha256']:raise ValueError('Protected saved13 changed')
    def user(self,label):
        if label=='after':self.after_guard_attempted=True
        raw=self.G['protected_snapshot']();self.artifact(label+'-user-raw',raw);self.saved()
        if self.before is not None:
            comparison=self.S['compare'](self.before,raw,self.spec);self.artifact(label+'-user-comparison',comparison)
            if not comparison['semantic_protection_equal']:raise ValueError('User packages changed')
        if label=='after':self.after_guard_verified=True
        return raw
    def verify_previous_current(self):
        previous=(self.snapshot or {}).get('previous_current')
        if previous and sha(previous['path'])!=previous['sha256']:raise ValueError('Previous user lastgood pointer changed')
    def affinity(self,label):
        mask=self.evaluation._ProcessAffinity().get();E.setdefault('affinity',[]).append(dict(stage=label,mask=mask))
        if mask!=65535:raise ValueError('Expected original process affinity65535')
    def setup(self):
        import sd,shiboken6,substance_physics_scatter
        from PySide6 import QtCore,QtWidgets
        from sd.api.apiexception import APIException
        from substance_physics_scatter import ui,designer,evaluation,graph_companion
        from substance_physics_scatter.ui_observation import current
        self.errors=(Exception,APIException);self.QtCore=QtCore;self.shiboken=shiboken6;self.ui=ui;self.designer=designer;self.evaluation=evaluation;self.companion=graph_companion
        evaluation._assert_environment();self.affinity('before')
        observation=current();self.artifact('ui-before',observation)
        self.panel=substance_physics_scatter._panel
        if self.panel is None or not isinstance(self.panel,ui.Panel) or not shiboken6.isValid(self.panel):raise ValueError('Canonical Panel is absent')
        state=observation.get('panel',{})
        if (observation.get('status')!='observed' or not observation.get('ui_thread') or state.get('operation_contract_available') is not True
                or state.get('operation_pending') is not False or state.get('operation_phase')!='idle' or state.get('closing') is not False
                or state.get('lifecycle_stopping') is not False or any(observation.get(k,{}).get('present') is not False for k in ('process','shutdown_process'))):raise ValueError('Canonical owner must be idle')
        self.panel_pointer=shiboken6.getCppPointer(self.panel)[0];self.snapshot=panel_snapshot(self.panel);self.artifact('previous-panel-settings',self.snapshot)
        self.manager=sd.getContext().getSDApplication().getPackageMgr();self.app=sd.getContext().getSDApplication()
        self.P=runpy.run_path(str(BASE/'ownership.py'));self.F=runpy.run_path(str(BASE/'probe_files.py'))
        self.G=runpy.run_path(str(BASE/'user_guard.py'));self.S=runpy.run_path(str(BASE/'enum_scope.py'))
        self.spec=self.F['read_json'](BASE/'enum_expected.json');prep=self.F['read_json'](BASE/'preparation.json')
        self.inventory_before=self.P['inventory'](self.manager);self.artifact('inventory-before',self.inventory_before)
        self.G['configure'](self.manager,self.ledger['owned']);self.before=self.user('before')
        original,asset_info=brick_asset(LIBRARY,BRICK);E['brick']=asset_info
        asset_path=own(WORK/'assets/brick_red.obj');asset_path.parent.mkdir()
        with asset_path.open('xb') as stream:stream.write(original)
        self.disks[str(asset_path)]=BRICK_SHA;self.identities={};prepared={}
        for role in ('noise','invert','source'):
            meta=copy.deepcopy(prep['packages'][role]);path=BASE/'prepared'/meta['relative_path']
            if sha(path)!=meta['sha256']:raise ValueError('Accepted source preparation changed')
            uid=str(uuid.uuid4());raw,proof=self.F['replace_top_uid'](path.read_bytes(),uid)
            target=own(WORK/'source'/meta['relative_path']);target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
            meta.update(uid=uid,sha256=sha(target));prepared[role]=meta;self.identities[role]=dict(path=str(target),uid=uid)
            self.disks[str(target)]=sha(target);self.artifact('uid-'+role,proof)
        for role in ('noise','invert','source'):
            self.artifact('load-'+role,self.P['load_one'](self.manager,role,self.identities[role],prepared[role],self.identities,self.ledger,self.inventory_before))
        self.source_before=self.source_states();self.target=self.create_target()
        self.install_process_counter()
        self.panel_modified=True
        self.panel.refresh();self.panel.nodes.setCurrentText(self.target['graph_identifier'])
        if self.panel._target_identity!=self.target:raise ValueError('Example target was not selected')
        self.panel.set_assets([dict(asset_id=uuid.uuid4().hex,path=str(asset_path),source_name='Hunyuan brick_red ·4998tri',format='obj',weight=1.,scale=1.)])
        for key,value in dict(count=20,width=1.5,depth=1.5,seed=1,seconds=6).items():getattr(self.panel,key).setValue(value)
        self.panel.edges.setCurrentText('walls');self.panel.height.setValue(1.);self.panel.normal.setCurrentText('OpenGL')
        if self.panel.resolution.findText('128')<0:self.panel.resolution.addItem('128')
        self.panel.resolution.setCurrentText('128');self.panel.set_mask({'enabled':False})
        selection=dict(package_path=self.identities['source']['path'],package_uid=self.identities['source']['uid'],graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        self.panel.source_choices.clear();self.panel.source_choices.addItem('Review · NativeMaskSource / native_mask',selection)
        E.update(source=self.identities['source']['path'],target=self.target,selection=selection,product_channels=['height','normal','coverage'],PBR=False,FBX=False)
        self.phase='wait_inspection';self.panel.inspect_source();self.remember_token();self.report()
    def source_states(self):return [r for r in self.P['states'](self.manager,self.ledger,self.inventory_before)['packages'] if r['role']!='target']
    def create_target(self):
        try:
            package=self.manager.newUserPackage();E['new_package']+=1;identity=self.P['package_id'](package)
            if identity['path'] is not None or any(r['uid']==identity['uid'] for r in self.P['expected'](self.ledger,self.inventory_before)) or self.P['inventory'](self.manager)!=self.P['order'](self.P['expected'](self.ledger,self.inventory_before)+[identity]):raise ValueError('Unknown new example package')
            row=dict(name='target',identity=identity,state='adopted');self.ledger['owned'].append(row)
            parent=self.designer.SDSBSCompGraph.sNew(package);parent.setIdentifier('GraphMaskReview')
            path=own(WORK/'Scatter.sbs');E['target_saves']+=1;self.manager.savePackageAs(package,str(path))
            after=self.P['package_id'](package)
            if after!=dict(uid=identity['uid'],path=str(path)):raise ValueError('Unknown example save identity')
            row['identity']=after;self.P['context'](self.manager,self.ledger,self.inventory_before)
            graph,_=self.designer.create(parent);self.disks[str(path)]=sha(path)
            return self.designer.scatter_identity(graph)
        except self.errors:self.P['ambiguous'](self.ledger,'Example creation/save ownership unknown');raise
    def remember_token(self):
        if self.panel._token is not None:self.owned_tokens.add(self.panel._token['id'])
    def install_process_counter(self):
        lane=self;QtCore=self.QtCore;ui=self.ui;real=QtCore.QProcess
        class Process(real):
            def start(process,executable,args):
                E['native_attempts']+=1
                if E['native_attempts']!=1 or len(args)!=1 or sha(executable)!=WORKER_SHA:raise ValueError('Exactly one pinned legacy worker required')
                path=own(Path(args[0]));request=json.loads(path.read_bytes())
                if request['operation']!='simulate_bake' or request['physics_input_format_version']!=2 or request['bake']['resolution']!=128 or request['simulation']['count']!=20:raise ValueError('Fixed example request differs')
                if any(request['simulation'][k]!=v for k,v in dict(width=1.5,depth=1.5,seed=1,seconds=6,edges='walls').items()) or request['bake']['height_max']!=1 or request['bake']['normal']!='OpenGL':raise ValueError('Fixed example dimensions/bake differ')
                lane.processes[id(process)]=dict(request=str(path),sha256=sha(path),bytes=0);E['native_starts']+=1;lane.report()
                QtCore.QTimer.singleShot(120000,lambda:lane.child_timeout(process))
                return super().start(executable,args)
            def readAllStandardOutput(process):
                raw=super().readAllStandardOutput();lane.log(process,'stdout',bytes(raw));return raw
            def readAllStandardError(process):
                raw=super().readAllStandardError();lane.log(process,'stderr',bytes(raw));return raw
        self.had_prepare='_prepare_and_start' in self.panel.__dict__;self.previous_prepare=self.panel.__dict__.get('_prepare_and_start')
        self.original_prepare=self.panel._prepare_and_start
        def prepare(panel,*args):
            if args[0]['id'] not in lane.owned_tokens:return lane.original_prepare(*args)
            previous=ui.QtCore;ui.QtCore=types.SimpleNamespace(QProcess=Process,QTimer=QtCore.QTimer,Qt=QtCore.Qt)
            try:return lane.original_prepare(*args)
            finally:ui.QtCore=previous
        self.panel._prepare_and_start=types.MethodType(prepare,self.panel)
    def restore_counter(self):
        if self.original_prepare is not None:
            if self.had_prepare:self.panel._prepare_and_start=self.previous_prepare
            else:del self.panel._prepare_and_start
            self.original_prepare=None
    def log(self,process,channel,raw):
        if not raw:return
        row=self.processes[id(process)];row['bytes']+=len(raw)
        if row['bytes']>4*1024*1024:process.kill();raise ValueError('Own child log4MiB cap')
        with own(WORK/('worker-'+channel+'.log')).open('ab') as stream:stream.write(raw)
    def child_timeout(self,process):
        if not self.finishing and self.panel.process is process and id(process) in self.processes and self.shiboken.isValid(process) and process.state()!=self.QtCore.QProcess.ProcessState.NotRunning:self.fail('Own worker120s timeout')
    def save_ready_target(self):
        record=next(r for r in self.P['active'](self.ledger) if r['name']=='target')
        try:
            package=self.P['canonical'](self.manager,record,self.ledger,self.inventory_before)
            E['target_saves']+=1;self.manager.savePackage(package)
            if self.P['package_id'](package)!=record['identity'] or package.isModified() is not False:raise ValueError('Saved example identity/modified differs')
            self.disks[record['identity']['path']]=sha(record['identity']['path'])
        except self.errors:self.P['ambiguous'](self.ledger,'Example final save ownership unverified');raise
    def open_source(self):
        try:
            record=next(r for r in self.P['active'](self.ledger) if r['name']=='source')
            package=self.P['canonical'](self.manager,record,self.ledger,self.inventory_before)
            graphs=[g for g in package.getChildrenResources(False) if isinstance(g,self.designer.SDSBSCompGraph) and g.getIdentifier()=='NativeMaskSource']
            if len(graphs)!=1:raise ValueError('Own source resource not unique')
            manager=self.app.getUIMgr()
            if manager is None:E['source_editor']=dict(opened=False,path=self.identities['source']['path'],reason='SDUIMgr unavailable');return
            manager.openResourceInEditor(graphs[0]);E['source_editor']=dict(opened=True,path=self.identities['source']['path'],API='SDUIMgr.openResourceInEditor')
        except self.errors as error:
            E['source_editor']=dict(opened=False,path=self.identities['source']['path'],reason=type(error).__name__+': '+str(error))
            error.__traceback__=None;error.__cause__=None;error.__context__=None
    def tick(self):
        if self.finishing:return
        try:
            if self.phase=='wait_failure':
                if self.panel._token is not None or self.panel.process is not None:
                    if time.monotonic()-self.started>=240:
                        self.finishing=True;self.restore_counter()
                        if self.inventory_before is not None:self.P['ambiguous'](self.ledger,'Own operation did not acknowledge cancellation by240s; no cleanup/full reader')
                        E.update(status='failed_unacknowledged',packages_require_owner_review=True)
                        self.report();self.timer.stop();self.timer.deleteLater()
                    return
                self.finish(False);return
            if time.monotonic()-self.started>240:raise TimeoutError('Example preparation240s')
            if self.phase=='setup':self.setup();return
            if self.panel._target_identity!=self.target:raise ValueError('Example target selection changed during preparation')
            if self.panel._token is not None or self.panel.process is not None:return
            self.affinity(self.phase)
            if self.phase=='wait_inspection':
                if self.panel._source_context is None:raise ValueError('Fresh inspection failed: '+self.panel.status.text())
                self.phase='wait_simulation';self.panel.run(False);self.remember_token()
            elif self.phase=='wait_simulation':
                current=self.panel.jobs.current
                if current is None:raise ValueError('No completed example: '+self.panel.status.text())
                self.designer.verify_metadata_current(self.designer.resolve_scatter(self.target),self.panel.jobs,current)
                self.companion.read(self.panel.jobs.directory,current)
                if E['native_starts']!=1 or current['request']['bake']['resolution']!=128:raise ValueError('Example did not execute its fixed native request')
                self.artifact('current-result',current);self.save_ready_target()
                self.designer.verify_metadata_current(self.designer.resolve_scatter(self.target),self.panel.jobs,current)
                E.update(job_id=current['job_id'],maps=current['files'],requested_count=current['result'].get('requested_count',20),spawned_count=len(current['result']['poses']),asset_cache=[dict(path=r['path'],sha256=r['content_hash']) for r in current['request']['assets']])
                self.open_source();self.finish(True);return
            self.report()
        except self.errors as error:
            message=type(error).__name__+': '+str(error);E['error_traceback']=traceback.format_exc()
            error.__traceback__=None;error.__cause__=None;error.__context__=None;self.fail(message)
    def fail(self,message):
        E.update(status='failed',error=message)
        if self.panel is not None and self.panel._token is not None:
            if self.panel._token['id'] in self.owned_tokens:
                self.panel.stop();self.phase='wait_failure';self.report();return
            if self.inventory_before is not None:self.P['ambiguous'](self.ledger,'Unowned panel operation; do not cancel/cleanup')
        self.finish(False)
    def restore_panel(self):
        previous=self.snapshot
        if previous is None:return
        self.panel.refresh();identity=previous['target']
        if identity is None:self.panel.nodes.setCurrentIndex(-1);self.panel.graph=None;self.panel.jobs=None;self.panel._target_identity=None
        else:
            matches=[i for i in range(self.panel.nodes.count()) if self.designer.scatter_identity(self.panel.nodes.itemData(i))==identity]
            if len(matches)!=1:raise ValueError('Previous target lifetime changed; cannot restore UI')
            self.panel.nodes.setCurrentIndex(matches[0]);self.panel.select()
        self.panel.set_assets(previous['assets']);self.panel.set_mask(previous['mask'])
        for key,value in previous['simulation'].items():getattr(self.panel,key).setValue(value)
        for key in ('edges','resolution','normal','mask_mode'):getattr(self.panel,key).setCurrentText(previous[key])
        self.panel.height.setValue(previous['height']);self.panel.source_choices.clear()
        for row in previous['source_items']:self.panel.source_choices.addItem(row['label'],row['value'])
        self.panel.source_choices.setCurrentIndex(previous['source_index']);self.panel.invalidate_source()
        self.panel.message('Example preparation failed; previous settings restored. Inspect a graph source again before Run.')
    def cleanup_failure(self):
        if not self.ledger['ambiguous'] and self.panel_modified:
            self.panel.invalidate_source();self.panel.graph=None;self.panel.jobs=None;self.panel._target_identity=None
            self.panel.nodes.blockSignals(True)
            try:self.panel.nodes.clear()
            finally:self.panel.nodes.blockSignals(False)
        E['cleanup']=self.P['cleanup'](self.manager,self.ledger,self.inventory_before,self.errors)
        final=self.P['inventory'](self.manager);self.artifact('inventory-final',final);self.saved()
        def protected():
            if not self.after_guard_attempted:return self.user('after')
            if not self.after_guard_verified:raise ValueError('Earlier after-user guard failed; no repeated snapshot')
        E['user_guard']=self.P['finish_guard'](self.ledger,final,self.inventory_before,self.before is not None,protected)
        if not E['user_guard']['verified']:raise ValueError('Preservation unverified; safe inventory/saved13 only')
        if self.panel_modified:self.restore_panel()
    def finish(self,success):
        if self.finishing:return
        self.finishing=True;self.restore_counter()
        try:
            if self.inventory_before is not None:
                if success:
                    self.P['context'](self.manager,self.ledger,self.inventory_before)
                    if len(self.P['active'](self.ledger))!=4 or self.source_states()!=self.source_before:raise ValueError('Prepared four-package source/ownership differs')
                    self.user('after');E['packages_retained']=copy.deepcopy(self.P['expected'](self.ledger,[]))
                else:
                    self.cleanup_failure()
                self.verify_previous_current()
                if any(sha(path)!=digest for path,digest in self.disks.items()) or sha(BRICK)!=BRICK_SHA:raise ValueError('Original/copied input bytes changed')
                self.affinity('final')
            if success:
                if self.panel._token is not None or self.panel.process is not None or self.panel._target_identity!=self.target:raise ValueError('Example is not selected and idle')
                E.update(status='GRAPH_MASK_REVIEW_READY',pending=False,native=1,packages_left_loaded=4,
                    help='Select this scatter and use Graph terminal Inspect/Simulate, or Bake saved pile. Three geometry maps only; PBR/FBX belongs to the separate local viewer.')
            else:E['status']='failed'
        except self.errors as error:
            E.update(status='failed_finalization',finalization_error=type(error).__name__+': '+str(error));error.__traceback__=None;error.__cause__=None;error.__context__=None
            if success and self.inventory_before is not None:
                try:self.cleanup_failure()
                except self.errors as cleanup:
                    E['failure_cleanup_error']=type(cleanup).__name__+': '+str(cleanup);cleanup.__traceback__=None;cleanup.__cause__=None;cleanup.__context__=None
        finally:
            E['native_records']=list(self.processes.values());self.report()
            if self.timer is not None:self.timer.stop();self.timer.deleteLater()


def schedule():
    global WORK,REPORT
    from PySide6 import QtCore,QtWidgets
    router=runpy.run_path(str(ROOT/'tests/designer_smoke_routes.py'));router['project_root']()
    WORK=router['owned'](ROOT,ROOT/'output/GraphMaskReview'/uuid.uuid4().hex);WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
    E.update(status='scheduled',work=str(WORK),native_attempts=0,native_starts=0,new_package=0,target_saves=0,
        limits=dict(native_children=1,child_seconds=120,log_bytes=4194304,wall_seconds=240,source_loads=3,new_package=1,target_saves=2),computer_use=False,screenshots=0)
    REPORT.write_text(json.dumps(E,indent=2),encoding='utf8')
    lane=Prepare();lane.timer=QtCore.QTimer(QtWidgets.QApplication.instance());lane.timer.setInterval(50);lane.timer.timeout.connect(lane.tick);lane.timer.start();return lane


if __name__=='__main__':LANE=schedule()
