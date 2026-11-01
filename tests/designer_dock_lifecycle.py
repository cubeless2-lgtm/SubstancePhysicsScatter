"""Explicit one-dock lifecycle lane. Run only for an idle coordinator-owned preview."""
from pathlib import Path
import hashlib,importlib,json,platform,sys,traceback,types,uuid
from unittest import mock
ROOT=Path(__file__).resolve().parents[1] if globals().get("__file__") and Path(__file__).name=="designer_dock_lifecycle.py" else Path("D:/Git/SubstancePhysicsScatter")
LANE=ROOT/"tests/designer_dock_lifecycle.py"
sys.path.insert(0,str(ROOT/"plugin"))
WORK=ROOT/"output/dock_lifecycle"/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/"report.json"
def fingerprint():
    paths=[p for p in (ROOT/"plugin").rglob("*.py")]+[LANE,ROOT/"build/Release/scatter_worker.exe"]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=fingerprint()
evidence={"status":"running","work":str(WORK),"job_id":WORK.name,"source_before":before,"steps":[],"native_attempts":0}
def report():
    evidence["source_after"]=fingerprint();evidence["inputs_unchanged"]=before==evidence["source_after"]
    REPORT.write_text(json.dumps(evidence,indent=2),encoding="utf-8")
    (ROOT/"output/evidence/dock-lifecycle-latest.json").write_text(json.dumps(evidence,indent=2),encoding="utf-8")
report()
try:
    import sd
    from PySide6 import QtCore,__version__ as pyside_version
    import substance_physics_scatter as scatter
    from substance_physics_scatter import errors,lifecycle,ui
    importlib.reload(errors);importlib.reload(lifecycle)
    HOST_ERRORS=errors.HOST_ERRORS
    app=sd.getContext().getSDApplication();manager=app.getPackageMgr()
    evidence["environment"]={"python":sys.version,"platform":platform.platform(),"designer":app.getVersion(),"qt":QtCore.qVersion(),"pyside":pyside_version}
    def packages():
        result={}
        for package in manager.getUserPackages():
            resources={}
            for resource in package.getChildrenResources(True):
                row={"class":resource.getClassName()}
                if hasattr(resource,"getNodes"):row["nodes"]=[(n.getIdentifier(),n.getDefinition().getId()) for n in resource.getNodes()]
                resources[resource.getIdentifier()]=row
            result[package.getUID()]={"path":package.getFilePath(),"modified":package.isModified(),"resources":resources}
        return result
    packages_before=packages()
    current_graph=app.getQtForPythonUIMgr().getCurrentGraph()
    current_url=current_graph.getUrl() if current_graph is not None else None
    state=lifecycle.qt_registry()
    if state.get("dock") is not None and not state.get("coordinator_preview"):
        raise RuntimeError("Existing panel is not owned by this lifecycle lane")
    if scatter._panel is not None and scatter._panel.process is not None:
        raise RuntimeError("An existing simulation is active")
    if state.get("failure"):raise RuntimeError("Previous native creation failed; no automatic retry is allowed")
    if state.get("dock") is None:
        if scatter._panel is not None:raise RuntimeError("An unregistered user panel exists; refusing replacement")
        importlib.reload(ui)
    source_path=ROOT/"plugin/substance_physics_scatter/ui.py"
    compiled=compile(source_path.read_text(encoding="utf-8"),str(source_path),"exec")
    expected_panel=next(value for value in compiled.co_consts if isinstance(value,types.CodeType) and value.co_name=="Panel")
    for method in expected_panel.co_consts:
        if isinstance(method,types.CodeType):
            assert getattr(ui.Panel,method.co_name).__code__==method,"Loaded Panel class does not match candidate source"
    evidence["latest_panel_code_verified"]=True
    state["coordinator_preview"]=True
    original=lifecycle.QtHost.create_dock
    def create_once(host,identifier):
        evidence["native_attempts"]+=1
        report()
        if evidence["native_attempts"]>1:raise RuntimeError("More than one native dock attempt in lifecycle lane")
        return original(host,identifier)
    with mock.patch.object(lifecycle.QtHost,"create_dock",create_once):
        importlib.reload(scatter)
        scatter.initializeSDPlugin();dock=scatter._dock;panel=scatter._panel
        assert lifecycle.QtHost.valid(dock) and lifecycle.QtHost.valid(panel)
        evidence["steps"].append("initialize");report()
        selected=(panel.nodes.currentText(),panel.mesh.text(),panel.count.value())
        scatter.initializeSDPlugin()
        assert scatter._dock is dock and scatter._panel is panel
        assert (panel.nodes.currentText(),panel.mesh.text(),panel.count.value())==selected
        evidence["steps"].append("idempotent_initialize");report()
        session=lifecycle.Session(state,lifecycle.QtHost(ui.Panel,app.getQtForPythonUIMgr()))
        session.hide();assert not dock.isVisible()
        evidence["steps"].append("hide_only");report()
        scatter.initializeSDPlugin();assert scatter._dock is dock and scatter._panel is panel and dock.isVisible()
        evidence["steps"].append("show_reuse");report()
        importlib.reload(scatter);scatter.initializeSDPlugin()
        assert scatter._dock is dock and scatter._panel is panel
        assert lifecycle.qt_registry() is state
        evidence["steps"].append("package_reload_reuse");report()
    assert packages()==packages_before,"User packages changed during panel lifecycle lane"
    active=app.getQtForPythonUIMgr().getCurrentGraph()
    assert (active.getUrl() if active is not None else None)==current_url,"Editor graph selection changed"
    evidence.update(status="pass",dock_identifier=state["dock_id"],user_packages_unchanged=True,editor_graph_unchanged=True)
    assert before==fingerprint();report()
except (Exception,errors.APIException if "errors" in globals() else Exception):
    evidence.update(status="failed",traceback=traceback.format_exc());report()
    raise RuntimeError("Dock lifecycle lane stopped; no native retry. Report: "+str(REPORT))
