"""Explicit shutdown acceptance; reuses only a coordinator-owned dock, never creates one."""
from pathlib import Path
import hashlib,importlib,json,platform,sys,traceback,uuid
from unittest import mock
ROOT=Path(__file__).resolve().parents[1] if globals().get("__file__") and Path(__file__).name=="designer_dock_shutdown.py" else Path("D:/Git/SubstancePhysicsScatter")
LANE=ROOT/"tests/designer_dock_shutdown.py"
sys.path.insert(0,str(ROOT/"plugin"));sys.path.insert(0,str(ROOT/"tests"))
WORK=ROOT/"output/dock_shutdown"/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/"report.json"
def fingerprint():
    paths=list((ROOT/"plugin").rglob("*.py"))+[LANE,ROOT/"build/Release/scatter_worker.exe"]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
before=fingerprint();evidence={"status":"running","job_id":WORK.name,"work":str(WORK),"source_before":before,"steps":[],"native_attempts":0}
def report():
    evidence["source_after"]=fingerprint();evidence["inputs_unchanged"]=before==evidence["source_after"]
    text=json.dumps(evidence,indent=2);REPORT.write_text(text,encoding="utf-8");(ROOT/"output/evidence/dock-shutdown-latest.json").write_text(text,encoding="utf-8")
report();pending_inputs=None;state=None;scatter=None
try:
    import sd,shiboken6
    from PySide6 import QtCore,__version__ as pyside_version
    import substance_physics_scatter as scatter
    from substance_physics_scatter import lifecycle,designer,core,errors
    from png_pixels import signature
    HOST_ERRORS=errors.HOST_ERRORS
    app=sd.getContext().getSDApplication();manager=app.getPackageMgr();state=lifecycle.qt_registry()
    evidence["environment"]={"python":sys.version,"platform":platform.platform(),"designer":app.getVersion(),"qt":QtCore.qVersion(),"pyside":pyside_version}
    if not state.get("coordinator_preview") or not lifecycle.QtHost.valid(state.get("dock")) or not lifecycle.QtHost.valid(state.get("panel")):
        raise RuntimeError("BLOCKED: a valid coordinator-owned preview dock/panel is required")
    if state.get("phase") not in ("ready","hidden") or state["panel"].process is not None:
        raise RuntimeError("BLOCKED: an active panel operation exists")
    if state["panel"].jobs is not None and state["panel"].jobs.active is not None:
        raise RuntimeError("BLOCKED: a pending preview job exists")
    dock=state["dock"];layout=state["layout"];initial_panel=state["panel"]
    def inputs(panel):
        return {"nodes":panel.nodes.currentText(),"mesh":panel.mesh.text(),
            **{name:getattr(panel,name).value() for name in ("count","scale","width","depth","seed","seconds","height")},
            **{name:getattr(panel,name).currentText() for name in ("edges","resolution","normal")},
            "status":panel.status.text(),"progress":panel.progress.value()}
    def restore(panel,values):
        panel.nodes.setCurrentText(values["nodes"]);panel.mesh.setText(values["mesh"])
        for name in ("count","scale","width","depth","seed","seconds","height"):getattr(panel,name).setValue(values[name])
        for name in ("edges","resolution","normal"):getattr(panel,name).setCurrentText(values[name])
        panel.status.setText(values["status"]);panel.progress.setValue(values["progress"])
        assert inputs(panel)==values,"Pending preview inputs were not restored"
    pending_inputs=inputs(initial_panel);evidence["pending_inputs_before"]=pending_inputs
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
    packages_before=packages();active=app.getQtForPythonUIMgr().getCurrentGraph();active_url=active.getUrl() if active is not None else None
    proof=json.loads((ROOT/"output/evidence/live-3e91eadc.json").read_text(encoding="utf-8"))
    accepted=json.loads((ROOT/proof["report"]).read_text(encoding="utf-8"));assert accepted["status"]=="pass"
    package=manager.getUserPackageFromFilePath(str(Path(accepted["run_directory"])/"PhysicsScatterDemo.sbs"))
    if package is None:raise RuntimeError("BLOCKED: the accepted coordinator test package is not open")
    graph=next((r for r in package.getChildrenResources(True) if r.getIdentifier()==accepted["nodes"][0]),None)
    if graph is None:raise RuntimeError("BLOCKED: accepted test scatter is unavailable")
    jobs=core.Jobs(designer.result_directory(graph));metadata_before=designer.settings(graph);pointer_before=core.digest(jobs.directory/"current.json")
    def pixels(label):
        target=WORK/label;designer.export_outputs(graph,target)
        return {name:signature(target/(name+".png")) for name in designer.CHANNELS}
    pixel_baseline=pixels("before")
    def unchanged(label):
        assert designer.settings(graph)==metadata_before,label+" changed graph metadata"
        assert core.digest(jobs.directory/"current.json")==pointer_before,label+" changed the accepted result pointer"
        assert pixels(label)==pixel_baseline,label+" changed decoded maps"
    def wait_until(predicate,timeout_ms=15000):
        loop=QtCore.QEventLoop();poll=QtCore.QTimer();poll.setInterval(5);watchdog=QtCore.QTimer();watchdog.setSingleShot(True)
        poll.timeout.connect(lambda:loop.quit() if predicate() else None);watchdog.timeout.connect(loop.quit)
        poll.start();watchdog.start(timeout_ms);loop.exec();poll.stop();watchdog.stop()
        if not predicate():raise TimeoutError("BLOCKED: async cleanup timed out; no forced child deletion or native recreation")
    callbacks=[]
    original_finished=lifecycle.QtHost.on_finished
    def capture_finished(process,callback):callbacks.append(callback);return original_finished(process,callback)
    def forbid_native(host,identifier):
        evidence["native_attempts"]+=1;report();raise RuntimeError("Native dock creation is forbidden in shutdown lane")
    with mock.patch.object(lifecycle.QtHost,"create_dock",forbid_native),mock.patch.object(lifecycle.QtHost,"on_finished",staticmethod(capture_finished)):
        scatter.uninitializeSDPlugin()
        assert state["panel"] is None and state["dock"] is dock and state["layout"] is layout
        assert state["coordinator_preview"] and state["phase"]=="hidden"
        # The host Python handler has not returned to its original Qt event loop yet.
        # Deliver only this already-detached idle plugin child's posted delete event;
        # a nested QEventLoop alone can otherwise defer it until the host handler returns.
        if shiboken6.isValid(initial_panel):
            assert initial_panel.parent() is None and initial_panel._lifecycle_stopping
            QtCore.QCoreApplication.sendPostedEvents(initial_panel,QtCore.QEvent.Type.DeferredDelete)
            evidence["idle_deferred_delete"]={"target":"coordinator_owned_detached_idle_plugin_child","targeted_only":True,"sdk_root_not_targeted":True,"dispatched":True}
        else:
            evidence["idle_deferred_delete"]={"targeted_only":True,"sdk_root_not_targeted":True,"dispatched":False,"already_deleted":True}
        wait_until(lambda:not shiboken6.isValid(initial_panel),2000)
        scatter.initializeSDPlugin();assert state["dock"] is dock and state["layout"] is layout
        assert scatter._panel is not initial_panel
        evidence["steps"].append("idle_shutdown_disposes_child_and_reuses_root");unchanged("after_idle");report()
        panel=scatter._panel;panel.nodes.setCurrentText(graph.getIdentifier())
        assert panel.graph.getIdentifier()==graph.getIdentifier()
        panel.mesh.setText(str(ROOT/"tests/fixtures/cube.obj"));panel.count.setValue(5000);panel.scale.setValue(.08);panel.seconds.setValue(120)
        panel.run(False);assert panel.process is not None
        process=panel.process;shutdown_called=[False]
        def shutdown_once():
            try:
                assert state["panel"] is panel and panel.process is process
                scatter.uninitializeSDPlugin();shutdown_called[0]=True
            except HOST_ERRORS as error:
                evidence["shutdown_callback_error"]=repr(error)
        QtCore.QTimer.singleShot(5,shutdown_once)
        wait_until(lambda:shutdown_called[0] and state["panel"] is None and state["phase"]=="hidden")
        assert callbacks,"Expected the real worker finished cleanup callback"
        unchanged("after_active");evidence["steps"].append("active_shutdown_waits_for_finished_and_preserves_result");report()
        old_callback=callbacks[-1];old_generation=state["generation"]
        scatter.initializeSDPlugin();replacement=scatter._panel
        assert replacement is not panel and state["generation"]>old_generation
        restore(replacement,pending_inputs)
        state_identity=(state["generation"],state["phase"],state["panel"],state["dock"],state["layout"])
        old_callback(9,QtCore.QProcess.ExitStatus.CrashExit)
        assert (state["generation"],state["phase"],state["panel"],state["dock"],state["layout"])==state_identity
        assert inputs(replacement)==pending_inputs
        unchanged("after_late_callback");evidence["steps"].append("late_callback_leaves_replacement_generation_unchanged")
    assert packages()==packages_before,"User package inventory or modified state changed"
    active=app.getQtForPythonUIMgr().getCurrentGraph();assert (active.getUrl() if active is not None else None)==active_url
    assert evidence["native_attempts"]==0 and before==fingerprint()
    evidence.update(status="pass",pending_inputs_restored=True,user_packages_unchanged=True,editor_graph_unchanged=True,metadata_pointer_pixels_unchanged=True);report()
except (Exception,errors.APIException if "errors" in globals() else Exception):
    evidence.update(status="blocked" if isinstance(sys.exception(),TimeoutError) else "failed",traceback=traceback.format_exc())
    if state is not None and pending_inputs is not None and lifecycle.QtHost.valid(state.get("panel")) and state.get("phase")!="stopping":
        try:restore(state["panel"],pending_inputs);evidence["pending_inputs_restored_on_failure"]=True
        except HOST_ERRORS as recovery:evidence["restore_error"]=repr(recovery)
    report();raise RuntimeError("Dock shutdown lane stopped; do not force cleanup. Report: "+str(REPORT))
