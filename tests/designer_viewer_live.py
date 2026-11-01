"""Root-only actual Graph edit/Sim/Saved/failure/cancel on the owned review example.

Fixed smoke lane; two enum-only continuation files pace browser observation.
No supplied code/paths, editor reload, package creation, or unrelated package save.
"""
from pathlib import Path
import copy,hashlib,json,time,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=None
REPORT=None
E={}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8'));temporary.replace(path)

class Lane:
    def __init__(self):self.phase='setup';self.start=time.monotonic();self.panel=None;self.timer=None;self.owned=set();self.finished=False
    def publish(self):
        E.update(phase=self.phase,elapsed_seconds=time.monotonic()-self.start);write(REPORT,E)
    def current(self):
        value=self.panel.jobs.current
        self.designer.verify_metadata_current(self.designer.resolve_scatter(self.target),self.panel.jobs,value)
        return value
    def identity(self):return sorted(str(p.getFilePath()) for p in self.manager.getUserPackages())
    def idle(self):return self.panel._token is None and self.panel.process is None
    def continuation(self,name,action):
        path=WORK/name
        if not path.exists():return False
        if path.is_symlink() or path.stat().st_size>128:raise ValueError('Continuation shape')
        if json.loads(path.read_text(encoding='utf8'))!={'action':action}:raise ValueError('Fixed continuation enum required')
        path.rename(path.with_suffix('.consumed'));return True
    def begin(self,rebake):
        self.panel.run(rebake)
        if self.panel._token is not None:self.owned.add(self.panel._token['id'])
    def setup(self):
        import sd,shiboken6,substance_physics_scatter
        from substance_physics_scatter import designer
        from PySide6 import QtCore
        self.QtCore=QtCore;self.designer=designer;self.shiboken=shiboken6
        latest=json.loads((ROOT/'output/GraphMaskReview/latest.json').read_text(encoding='utf8'))
        self.target=latest['target'];directory=Path(latest['directory'])
        if directory.parent!=ROOT/'output/GraphMaskReview' or len(directory.name)!=32:raise ValueError('Owned example boundary')
        self.panel=substance_physics_scatter._panel
        if self.panel is None or not self.idle() or self.panel._target_identity!=self.target:raise ValueError('Example canonical panel must be selected and idle')
        self.panel_pointer=shiboken6.getCppPointer(self.panel)[0]
        self.manager=sd.getContext().getSDApplication().getPackageMgr();self.inventory=self.identity()
        self.initial=self.current();self.rows=copy.deepcopy(self.panel.asset_rows());self.resolution=self.panel.resolution.currentText()
        write(WORK/'before-current.json',self.initial)
        self.source_path=Path(latest['source']);self.target_path=Path(self.target['package_path'])
        if self.source_path!=directory/'source/Source.sbs' or self.target_path!=directory/'Scatter.sbs':raise ValueError('Fixed source/target')
        sources=[p for p in self.manager.getUserPackages() if p.getFilePath() and Path(p.getFilePath()).resolve()==self.source_path.resolve()]
        if len(sources)!=1:raise ValueError('Unique loaded review source required')
        self.source_package=sources[0]
        graphs=[g for g in self.source_package.getChildrenResources(True) if isinstance(g,designer.SDSBSCompGraph) and g.getIdentifier()=='NativeMaskSource']
        if len(graphs)!=1:raise ValueError('Unique source graph')
        self.source=graphs[0]
        nodes=[n for n in self.source.getNodes() if str(n.getIdentifier())=='1585448170']
        if len(nodes)!=1:raise ValueError('Exact owned invert node')
        self.invert=nodes[0];self.old_invert=bool(self.invert.getInputPropertyValueFromId('invert').get())
        # A prior rejected inspection may already have left the requested True
        # edit saved while the first, False-mask native current remains intact.
        self.new_invert=True if self.initial['job_id']==latest['job_id'] else not self.old_invert
        for label,path in (('Source.sbs',self.source_path),('Scatter.sbs',self.target_path)):
            (WORK/('before-'+label)).write_bytes(path.read_bytes())
        E.update(initial_job=self.initial['job_id'],initial_mask=self.initial['request']['scatter_mask']['content_hash'],invert_before=self.old_invert,inventory_before=self.inventory,panel_pointer=self.panel_pointer)
        self.phase='ready';self.publish()
    def edit_and_inspect(self):
        from sd.api.sdvaluebool import SDValueBool
        self.invert.setInputPropertyValueFromId('invert',SDValueBool.sNew(self.new_invert))
        self.manager.savePackage(self.source_package)
        if self.source_package.isModified():raise ValueError('Owned source save failed')
        selection=dict(package_path=str(self.source_path),package_uid=str(self.source_package.getUID()),graph_identifier='NativeMaskSource',terminal_identifier='native_mask')
        self.panel.source_choices.clear();self.panel.source_choices.addItem('Review · NativeMaskSource / native_mask',selection)
        self.phase='wait_inspect';self.panel.inspect_source()
        if self.panel._token is not None:self.owned.add(self.panel._token['id'])
        E.update(invert_after=self.new_invert,resumed_saved_edit=self.old_invert==self.new_invert,source_saved_sha256=sha(self.source_path))
    def failure_cancel(self):
        stable=self.current();pointer=self.panel.jobs.directory/'current.json';before=sha(pointer)
        try:
            rows=copy.deepcopy(self.rows);rows[0]['path']=str(WORK/'deliberately-missing.obj');self.panel.set_assets(rows)
            self.begin(False)
            if not self.idle() or sha(pointer)!=before or 'Invalid asset' not in self.panel.status.text():raise ValueError('Real UI input failure did not retain current')
            E['actual_input_failure']=dict(message=self.panel.status.text(),job_id=self.current()['job_id'],pointer_unchanged=True)
        finally:self.panel.set_assets(self.rows)
        self.phase='wait_cancel';self.begin(False)
        if self.panel._token is None:raise ValueError('Queued operation required before cancel')
        self.panel.stop();self.stable_pointer=before;self.stable_job=stable['job_id']
    def finish(self,status):
        if self.finished:return
        self.finished=True
        try:
            if self.panel is not None and not self.idle():raise ValueError('Owned operation still pending; no cleanup')
            if self.panel is not None:
                self.panel.set_assets(self.rows)
                if self.identity()!=self.inventory or self.shiboken.getCppPointer(self.panel)[0]!=self.panel_pointer:raise ValueError('User inventory/canonical panel identity changed')
                if status=='PASS':
                    package=self.designer.resolve_scatter(self.target).getPackage();self.manager.savePackage(package)
                    self.current();E['target_saved_sha256']=sha(self.target_path)
            E['status']=status
        except Exception:E.update(status='FAILED_FINALIZE',finalization_traceback=traceback.format_exc())
        self.phase='finished';self.publish();self.timer.stop();self.timer.deleteLater()
    def tick(self):
        if self.finished:return
        try:
            if time.monotonic()-self.start>600:raise TimeoutError('Fixed lane600s deadline')
            if self.phase=='setup':self.setup();return
            if self.phase=='ready':
                if self.continuation('start.json','change_graph_and_simulate'):self.edit_and_inspect();self.publish()
                return
            if not self.idle():return
            if self.phase=='wait_inspect':
                if self.panel._source_context is None:raise ValueError('Fresh source inspection failed: '+self.panel.status.text())
                self.phase='wait_simulation';self.begin(False)
            elif self.phase=='wait_simulation':
                value=self.current()
                if value['job_id']==self.initial['job_id'] or value['request']['scatter_mask']['content_hash']==E['initial_mask'] or value['result']['poses']==self.initial['result']['poses']:raise ValueError('Graph change must create new mask, native job and placement')
                write(WORK/'simulation-current.json',value);self.sim=copy.deepcopy(value)
                E['simulation_job']=value['job_id'];E['simulation_mask']=value['request']['scatter_mask']['content_hash'];E['simulation_poses']=len(value['result']['poses'])
                self.phase='simulation_ready'
            elif self.phase=='simulation_ready':
                if not self.continuation('rebake.json','rebake_256'):return
                if self.panel.resolution.findText('256')<0:self.panel.resolution.addItem('256')
                self.panel.resolution.setCurrentText('256');self.phase='wait_rebake';self.begin(True)
            elif self.phase=='wait_rebake':
                value=self.current()
                if value['job_id']==self.sim['job_id'] or value['request']['bake']['resolution']!=256 or value['result']['poses']!=self.sim['result']['poses'] or value['result']['execution']!={'physics_executed':False,'body_count':0,'steps':0}:raise ValueError('Saved must change bake/job and preserve poses without physics')
                write(WORK/'saved-current.json',value);E['saved_job']=value['job_id'];E['saved_resolution']=256;E['saved_physics_executed']=False
                self.failure_cancel()
            elif self.phase=='wait_cancel':
                if sha(self.panel.jobs.directory/'current.json')!=self.stable_pointer or self.current()['job_id']!=self.stable_job:raise ValueError('Cancel changed lastgood')
                E['actual_queued_cancel']=dict(job_id=self.stable_job,pointer_unchanged=True,message=self.panel.status.text())
                self.finish('PASS');return
            self.publish()
        except Exception:
            E.update(status='FAILED',traceback=traceback.format_exc())
            if self.panel is not None and not self.idle():
                if self.panel._token is not None and self.panel._token['id'] in self.owned:self.panel.stop()
                self.publish();self.timer.stop();return
            self.finish('FAILED')

def schedule():
    global WORK,REPORT
    from PySide6 import QtCore,QtWidgets
    WORK=ROOT/'output/designer_bridge/viewer-live'/uuid.uuid4().hex;WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
    E.update(status='scheduled',work=str(WORK),computer_use=False)
    write(REPORT,E);lane=Lane();lane.timer=QtCore.QTimer(QtWidgets.QApplication.instance());lane.timer.setInterval(100);lane.timer.timeout.connect(lane.tick);lane.timer.start();return lane

if __name__=='__main__':LANE=schedule()
