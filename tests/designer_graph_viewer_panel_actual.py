"""Isolated Qt Graph capture → isolated viewer run → Designer apply smoke lane.

The coordinator must run an owned, isolated viewer at 127.0.0.1:8879 and
submit its test draft before invoking this fixed lane. Never targets port 8765.
"""
from pathlib import Path
import copy,hashlib,importlib,json,runpy,time,traceback,types,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/evidence/h2-first-capture-probe/a72703984c254876a32475cbb336a1da'
WORK=ROOT/'output/gv'/uuid.uuid4().hex[:12]
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
report={'status':'scheduled','work':str(WORK),'viewer':'127.0.0.1:8879'}
def write():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
write()
import sd
from PySide6 import QtCore
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from substance_physics_scatter import ui,designer,designer_external,lifecycle
importlib.reload(ui);importlib.reload(designer_external)
app=sd.getContext().getSDApplication();mgr=app.getPackageMgr();registry=lifecycle.qt_registry();canonical=registry.get('panel')
original={str(p.getUID()) for p in mgr.getUserPackages()}
state={'owned':[],'panel':None,'timer':None,'phase':'setup','started':time.monotonic()}
def read(path,limit=2*1024*1024):
    with urllib.request.urlopen('http://127.0.0.1:8879'+path,timeout=5) as response:
        raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('Isolated viewer response too large')
    return json.loads(raw)
def finish(status,error=None):
    timer=state.get('timer')
    if timer is not None:timer.stop()
    panel=state.get('panel')
    if panel is not None:
        try:
            if panel._token is not None or panel.process is not None:raise ValueError('Cannot unload owned package while panel operation is pending')
            panel.graph=None;panel.jobs=None;panel._target_identity=None
            for combo in (panel.nodes,panel.source_choices):combo.blockSignals(True);combo.clear();combo.blockSignals(False)
            panel.close();panel.deleteLater()
        except BaseException as e:status='FAIL';report['panel_cleanup_error']=repr(e)
    if status=='PASS' or panel is None or panel._token is None:
        for package in reversed(state['owned']):
            try:mgr.unloadUserPackage(package)
            except BaseException as e:status='FAIL';report.setdefault('unload_errors',[]).append(repr(e))
    if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
    report['status']=status
    if error:report['traceback']=error
    write();registry.pop('_graph_viewer_panel_actual',None)
def select(panel,identifier):
    matches=[i for i in range(panel.nodes.count()) if panel.nodes.itemData(i) is not None and panel.nodes.itemData(i).getIdentifier()==identifier]
    if len(matches)!=1:raise ValueError('Own scatter selection differs')
    panel.nodes.setCurrentIndex(matches[0])
    if panel.graph is None or panel.graph.getIdentifier()!=identifier:raise ValueError('Own scatter selection failed')
def poll():
    try:
        if time.monotonic()-state['started']>240:raise TimeoutError('Graph viewer flow timed out; no retry')
        panel=state['panel']
        if panel._token is not None or panel.process is not None:return
        if state['phase']=='inspect':
            if panel._source_selection is None or panel._source_context is None:raise ValueError('Graph inspect failed: '+panel.status.text())
            state['phase']='run';panel.viewer_graph_run.click()
            if panel._token is None:raise ValueError('Graph run did not start: '+panel.status.text())
            return
        if state['phase']=='run':
            if not panel.status.text().startswith('Viewer simulation completed.'):raise ValueError('Graph viewer run failed: '+panel.status.text())
            server=read('/api/state');current=server.get('current') or {};job=current.get('job_id')
            if not job or job==state['previous_job']:raise ValueError('Isolated viewer did not promote a new job')
            settings=current['settings']['snapshot']
            if not settings.get('mask_id') or not settings.get('graph_mask_provenance_sha256'):raise ValueError('Graph mask and provenance absent from viewer result')
            report.update(job_id=job,mask_id=settings['mask_id'],provenance_sha256=settings['graph_mask_provenance_sha256'],run_message=panel.status.text())
            state['phase']='apply';panel.viewer_apply.click()
            if panel._token is None:raise ValueError('Panel apply did not start: '+panel.status.text())
            return
        if state['phase']=='apply':
            graph=designer.resolve_scatter(state['target']);meta=designer.settings(graph) or {};external=meta.get('external_current') or {}
            if external.get('job_id')!=report['job_id']:raise ValueError('Applied graph job differs: '+panel.status.text())
            links=designer_external.connection_snapshot(graph,designer)
            if set(row[0] for row in links)!=set(external['channels']):raise ValueError('Applied output channels differ')
            report.update(channels=external['channels'],applied=True,canonical_preserved=True,graph_capture_to_viewer=True)
            finish('PASS')
    except BaseException:finish('FAIL',traceback.format_exc())
try:
    draft=read('/api/designer-draft');current=read('/api/state').get('current')
    if not isinstance(draft,dict) or not draft.get('revision'):raise ValueError('Owned test viewer draft not submitted')
    state['previous_job']=current.get('job_id') if current else None
    prep=json.loads((BASE/'preparation.json').read_text(encoding='utf8'));helpers=runpy.run_path(str(BASE/'probe_files.py'))
    identities={}
    for role in ('noise','invert','source'):
        meta=prep['packages'][role];source=BASE/'prepared'/meta['relative_path'];raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('Prepared source identity differs')
        uid=str(uuid.uuid4());raw,_=helpers['replace_top_uid'](raw,uid)
        target=WORK/'source'/meta['relative_path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        identities[role]={'path':str(target),'uid':uid}
    for role in ('noise','invert','source'):
        package=mgr.loadUserPackage(identities[role]['path'],False,False)
        if package is None or str(package.getUID()).strip('{}').lower()!=identities[role]['uid'].strip('{}').lower() or str(package.getUID()) in original:raise ValueError('Owned source package identity differs')
        state['owned'].append(package)
    package=mgr.newUserPackage()
    if str(package.getUID()) in original or package.getFilePath():raise ValueError('Own target package identity differs')
    state['owned'].append(package);parent=SDSBSCompGraph.sNew(package);parent.setIdentifier('GraphViewerPanelSmoke')
    mgr.savePackageAs(package,str(WORK/'GraphViewerPanelSmoke.sbs'))
    graph,_=designer.create(parent);state['target']=designer.scatter_identity(graph)
    panel=ui.Panel();state['panel']=panel
    panel.local_viewer_url=types.MethodType(lambda self:'http://127.0.0.1:8879/',panel)
    select(panel,graph.getIdentifier());panel.source_choices.clear()
    panel.source_choices.addItem('Isolated NativeMaskSource/native_mask',dict(package_path=identities['source']['path'],package_uid=identities['source']['uid'],graph_identifier='NativeMaskSource',terminal_identifier='native_mask'))
    state['phase']='inspect';timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(100);timer.timeout.connect(poll)
    registry['_graph_viewer_panel_actual']=state;panel.inspect_source();timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
