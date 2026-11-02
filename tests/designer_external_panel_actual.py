"""Actual Qt panel handoff against an isolated, newly created Designer package."""
from pathlib import Path
import copy,importlib,json,time,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/external-panel-actual'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json'
report={'status':'scheduled','work':str(WORK)}
def write():REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
write()

import sd
from PySide6 import QtCore
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from substance_physics_scatter import designer,designer_external,ui,lifecycle
importlib.reload(designer_external);importlib.reload(ui)
app=sd.getContext().getSDApplication();mgr=app.getPackageMgr()
registry=lifecycle.qt_registry();canonical=registry.get('panel')
original_ids={str(p.getUID()) for p in mgr.getUserPackages()}
state={'panel':None,'package':None,'timer':None,'phase':'setup','started':time.monotonic()}

def finish(status,error=None):
    timer=state.get('timer')
    if timer is not None:timer.stop()
    panel=state.get('panel')
    if panel is not None:
        try:panel.close();panel.deleteLater()
        except BaseException as e:status='FAIL';report['panel_cleanup_error']=repr(e)
    package=state.get('package')
    if package is not None:
        try:mgr.unloadUserPackage(package)
        except BaseException as e:status='FAIL';report['package_cleanup_error']=repr(e)
    if registry.get('panel') is not canonical:status='FAIL';report['canonical_changed']=True
    report['status']=status
    if error is not None:report['traceback']=error
    write()
    registry.pop('_external_panel_actual',None)

def select(panel,identifier):
    matches=[i for i in range(panel.nodes.count()) if panel.nodes.itemData(i) is not None and panel.nodes.itemData(i).getIdentifier()==identifier]
    if len(matches)!=1:raise ValueError('Isolated scatter selection not unique')
    panel.nodes.setCurrentIndex(matches[0])
    if panel.graph is None or panel.graph.getIdentifier()!=identifier:raise ValueError('Isolated scatter selection failed')

def poll():
    try:
        if time.monotonic()-state['started']>90:raise TimeoutError('Panel handoff smoke exceeded 90 seconds')
        panel=state['panel']
        if panel._token is not None or panel.process is not None:return
        if state['phase']=='apply':
            graph=designer.resolve_scatter(state['first_identity']);metadata=designer.settings(graph) or {}
            external=metadata.get('external_current')
            if not isinstance(external,dict) or not external.get('job_id'):raise ValueError('Panel did not apply viewer result: '+panel.status.text())
            snapshot=designer_external.connection_snapshot(graph,designer)
            if set(x[0] for x in snapshot)!=set(designer_external.HNC+designer_external.PBR):raise ValueError('Panel output channels differ')
            state['first_metadata']=copy.deepcopy(metadata);state['first_connections']=snapshot
            report.update(applied_job=external['job_id'],channels=list(external['channels']),after_apply_status=panel.status.text())
            # Start a second transfer and immediately switch to another isolated target.
            # The selection handler cancels the first target before Qt can deliver HTTP.
            panel.viewer_apply.click()
            if panel._token is None:raise ValueError('Second panel transfer did not start')
            select_index=next(i for i in range(panel.nodes.count()) if panel.nodes.itemData(i) is not None and panel.nodes.itemData(i).getIdentifier()==state['second_id'])
            panel.nodes.setCurrentIndex(select_index)
            state['phase']='cancel';return
        if state['phase']=='cancel':
            graph=designer.resolve_scatter(state['first_identity'])
            if designer.settings(graph)!=state['first_metadata'] or designer_external.connection_snapshot(graph,designer)!=state['first_connections']:raise ValueError('Target switch changed previously applied result')
            second=designer.resolve_scatter(state['second_identity'])
            if (designer.settings(second) or {}).get('external_current'):raise ValueError('Cancelled transfer applied to the second graph')
            report.update(target_switch_cancellation_preserved=True,canonical_panel_preserved=True,isolated_package_only=True)
            finish('PASS')
    except BaseException:finish('FAIL',traceback.format_exc())

try:
    package=mgr.newUserPackage();state['package']=package
    if str(package.getUID()) in original_ids or package.getFilePath():raise ValueError('New package ownership differs')
    parent=SDSBSCompGraph.sNew(package);parent.setIdentifier('ExternalPanelSmoke')
    mgr.savePackageAs(package,str(WORK/'ExternalPanelSmoke.sbs'))
    first,_=designer.create(parent);second,_=designer.create(parent)
    state['first_identity']=designer.scatter_identity(first);state['second_identity']=designer.scatter_identity(second);state['second_id']=second.getIdentifier()
    panel=ui.Panel();state['panel']=panel;select(panel,first.getIdentifier())
    state['phase']='apply';timer=QtCore.QTimer();state['timer']=timer;timer.setInterval(50);timer.timeout.connect(poll)
    registry['_external_panel_actual']=state
    panel.viewer_apply.click()
    if panel._token is None:raise ValueError('Panel apply did not start: '+panel.status.text())
    timer.start()
except BaseException:finish('FAIL',traceback.format_exc())
