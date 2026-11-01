"""Closed local-file development bridge with Qt lifetime and process ownership."""
from __future__ import annotations
import json
from pathlib import Path
import re
import time
import traceback
import uuid
import os
import warnings
from datetime import datetime,timezone
from .core import atomic_json
from .errors import HOST_ERRORS

OPERATIONS = {"health", "inspect", "smoke", "stop", "ui_status"}
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_timer = None
_queue = None

class FileQueue:
    """One atomic request at a time. Responses are immutable by job identity."""
    def __init__(self, root, handler, *, maximum=128, lifetime=3600):
        self.root=Path(root).resolve()
        self.directory=self.root/"output/designer_bridge"
        self.directory.mkdir(parents=True,exist_ok=True)
        if not self.directory.resolve().is_relative_to(self.root):
            raise ValueError("Bridge directory escapes project root")
        self.responses=self.directory/"responses"
        self.quarantine=self.directory/"quarantine"
        for directory in (self.responses,self.quarantine):
            directory.mkdir(exist_ok=True)
            if not directory.resolve().is_relative_to(self.root):
                raise ValueError("Bridge subdirectory escapes project root")
        self.handler=handler
        self.maximum=maximum
        self.expires=time.monotonic()+lifetime
        self.processed=set()
        self.attempts=0
        self.busy=False
        self.stopped=False
        self.stop_reason=None
        self.last_error=None

    def tick(self):
        if self.busy or self.stopped:return
        if self.attempts>=self.maximum or time.monotonic()>=self.expires:
            self.stopped=True;self.stop_reason="request_limit" if self.attempts>=self.maximum else "expired";return
        if (self.directory/"processing.json").exists() or (self.directory/"processing.json").is_symlink():
            self.stopped=True;self.stop_reason="inflight_unknown";self.last_error="Existing processing.json requires inspection; never replayed";return
        request_path=self.directory/"request.json"
        if not request_path.exists() and not request_path.is_symlink():return
        self.busy=True
        self.last_error=None
        job_id=None
        processing=self.directory/"processing.json"
        try:
            request_path.replace(processing)
            self.attempts+=1
            # Move the directory entry before validating. A symlink target is never opened,
            # modified or deleted; only the link itself is moved into project-owned quarantine.
            if processing.is_symlink() or processing.stat().st_size>4096:
                processing.replace(self.quarantine/(uuid.uuid4().hex+".request"))
                raise ValueError("Invalid request file quarantined")
            request=json.loads(processing.read_text(encoding="utf-8"))
            job_id=request.get("job_id")
            operation=request.get("operation")
            if not isinstance(job_id,str) or not JOB_ID.fullmatch(job_id):
                raise ValueError("Invalid job_id")
            if set(request)!={"job_id","operation"} or operation not in OPERATIONS:
                raise ValueError("Only health/inspect/smoke/stop/ui_status operations are accepted")
            response=self.responses/(job_id+".json")
            if response.exists() or job_id in self.processed:
                # Never replace a successful response when an identity is reused.
                atomic_json(self.directory/"rejection.json",{"job_id":job_id,"status":"rejected","reason":"duplicate"})
                return
            self.processed.add(job_id)
            if operation=="stop":
                result={"stopped":True};self.stopped=True;self.stop_reason="explicit_stop"
            else:
                result=self.handler(operation)
            atomic_json(response,{"job_id":job_id,"operation":operation,"status":"completed","result":result})
        except HOST_ERRORS:
            self.last_error=traceback.format_exc()
            response=(self.responses/(job_id+".json")) if isinstance(job_id,str) and JOB_ID.fullmatch(job_id) else self.directory/"rejection.json"
            if not response.exists():
                atomic_json(response,{"job_id":job_id,"status":"error","traceback":traceback.format_exc()})
        finally:
            if processing.exists() or processing.is_symlink():processing.unlink()
            self.busy=False

def _execute(root,operation):
    if operation=="ui_status":
        from .ui_observation import current
        return current()
    if operation=="health":
        import sys
        return {"python":sys.version,"root":str(root),"operations":sorted(OPERATIONS)}
    if operation=="inspect":
        from .designer import application,settings,SDSBSCompGraph
        packages=[]
        for package in application().getPackageMgr().getUserPackages():
            graphs=[]
            for resource in package.getChildrenResources(True):
                if isinstance(resource,SDSBSCompGraph):
                    graphs.append({"identifier":resource.getIdentifier(),"scatter":bool(settings(resource)),"nodes":len(resource.getNodes())})
            packages.append({"path":package.getFilePath(),"graphs":graphs})
        return {"packages":packages}
    if operation=="smoke":
        import runpy
        import substance_physics_scatter
        panel=substance_physics_scatter._panel
        if panel is not None and (panel.process is not None or getattr(panel,"_token",None) is not None or getattr(panel,"_closing",False) or getattr(panel,"_phase","idle")!="idle"):
            raise RuntimeError("A user simulation is active; retry the test after it finishes")
        script=(root/"tests/designer_smoke.py").resolve()
        if not script.is_relative_to(root):raise ValueError("Test path escapes project")
        # Fixed project-owned script; incoming requests cannot choose a script or supply code.
        namespace=runpy.run_path(str(script),run_name="__main__")
        return json.loads(namespace["REPORT"].read_text(encoding="utf-8"))
    raise ValueError("Unknown operation")

ANCHOR_KEY="substance_physics_scatter_bridge_v1"

def development_root():
    module=Path(__file__).resolve();root=module.parents[2]
    if module!=root/"plugin/substance_physics_scatter/bridge.py":raise ValueError("Bridge is not in a development checkout")
    for relative in ("tests/designer_smoke.py","CMakeLists.txt","plugin/substance_physics_scatter/__init__.py"):
        path=root/relative
        if not path.is_file() or not path.resolve().is_relative_to(root):raise ValueError("Development markers missing or external")
    return root

class Lease:
    """Cooperating processes hold this OS lock across automatic session renewal."""
    def __init__(self,root):
        directory=Path(root)/"output/designer_bridge";directory.mkdir(parents=True,exist_ok=True);path=directory/"bridge_owner.lock"
        if not directory.resolve().is_relative_to(root) or path.is_symlink() or not path.resolve().is_relative_to(root):raise ValueError("Bridge lock escapes project")
        self.stream=path.open("a+b")
        try:
            if self.stream.seek(0,2)==0:self.stream.write(b"0");self.stream.flush()
            self.stream.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except HOST_ERRORS:
            self.stream.close();raise RuntimeError("Another live bridge owns this project; status and requests preserved") from None
    def close(self):
        if self.stream.closed:return
        self.stream.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close()

class Manager:
    version=1
    def __init__(self,root,timer):
        self.root=Path(root).resolve();self.timer=timer;self.queue=None;self.lease=None
        self.managed=False;self.latched=False;self.reason=None;self.session=None;self.last_session=None
        self.error=None;self.last_publish=0.;self.last_payload=None;self.last_warning=None
        timer.timeout.connect(self.poll)
    def view(self):
        q=self.queue
        fatal=self.error or (q.last_error if q is not None and q.stop_reason=="inflight_unknown" else None)
        status="stopping" if self.latched and q is not None and q.busy else "error" if fatal else "stopped" if self.latched else "expired" if q is not None and q.stopped else "listening" if q is not None else "inactive"
        return dict(version=2,status=status,root=str(self.root),pid=os.getpid(),session=self.session,managed=self.managed,stop_latched=self.latched,reason=self.reason,busy=bool(q and q.busy),attempts=q.attempts if q else 0,maximum_requests=128,lifetime_seconds=3600,expires_in_seconds=max(0.,q.expires-time.monotonic()) if q else 0.,operations=sorted(OPERATIONS),last_session=self.last_session,error=fatal,last_request_error=q.last_error if q is not None and q.stop_reason!="inflight_unknown" else None)
    def publish(self,force=False):
        if self.lease is None:return
        payload=self.view();signature={k:v for k,v in payload.items() if k!="expires_in_seconds"}
        if not force and signature==self.last_payload and time.monotonic()-self.last_publish<1:return
        payload["heartbeat_utc"]=datetime.now(timezone.utc).isoformat()
        atomic_json(self.root/"output/designer_bridge/bridge_status.json",payload);self.last_payload=signature;self.last_publish=time.monotonic()
    def renew(self):
        if self.queue is not None and self.queue.busy:raise RuntimeError("Cannot replace an executing bridge handler")
        if self.queue is not None:self.last_session=dict(session=self.session,reason=self.queue.stop_reason,attempts=self.queue.attempts)
        self.queue=FileQueue(self.root,lambda op:_execute(self.root,op));self.session=uuid.uuid4().hex;self.error=None;self.reason=None
        global _queue,_timer
        _queue=self.queue;_timer=self.timer
    def begin(self,managed,*,explicit=False):
        if self.latched and not explicit:return self.view()
        if self.queue is not None and self.queue.busy:
            if not explicit:return self.view()
            raise RuntimeError("Cannot replace an executing bridge handler")
        if self.queue is not None and self.timer.isActive() and not explicit:return self.view()
        if self.lease is None:self.lease=Lease(self.root)
        self.managed=managed;self.latched=False
        try:
            self.renew()
            processing=self.queue.directory/"processing.json"
            if processing.exists() or processing.is_symlink():
                self.queue.last_error="Existing processing.json requires inspection; never replayed";self.finish_stop("inflight_unknown");return self.view()
            self.publish(True);self.timer.start(250)
        except HOST_ERRORS:
            self.error=traceback.format_exc();self.finish_stop("start_error");raise
        return self.view()
    def finish_stop(self,reason):
        self.latched=True;self.reason=reason
        if self.queue is not None:self.queue.stopped=True;self.queue.stop_reason=reason
        self.timer.stop()
        try:self.publish(True)
        finally:
            if self.lease is not None:self.lease.close();self.lease=None
    def stop(self,reason="explicit_stop"):
        self.latched=True;self.reason=reason
        if self.queue is not None and self.queue.busy:self.publish(True);return
        self.finish_stop(reason)
    def poll(self):
        q=self.queue
        if q is None or q.busy:return
        try:
            if self.latched:self.finish_stop(self.reason or "explicit_stop");return
            q.tick()
            if self.latched:self.finish_stop(self.reason or "explicit_stop");return
            if q.stopped:
                if self.managed and q.stop_reason in ("expired","request_limit"):
                    self.reason=q.stop_reason;self.publish(True);self.renew()
                else:self.finish_stop(q.stop_reason or "stopped");return
            self.publish()
        except HOST_ERRORS:
            self.error=traceback.format_exc()
            try:self.finish_stop("poll_error")
            except HOST_ERRORS:self.error+="\nStatus/lock cleanup failed: "+traceback.format_exc()
            if self.last_warning!=self.error:warnings.warn("Physics Scatter bridge error: "+self.error,RuntimeWarning);self.last_warning=self.error

def _manager(root=None,*,create=False):
    from PySide6 import QtCore,QtWidgets
    import shiboken6
    app=QtWidgets.QApplication.instance()
    if app is None or not shiboken6.isValid(app) or QtCore.QThread.currentThread()!=app.thread():raise RuntimeError("Bridge requires the live Designer UI thread")
    anchor=app.property(ANCHOR_KEY)
    if anchor is None:
        if not create:return None
        anchor=QtCore.QObject(app);anchor.setObjectName(ANCHOR_KEY);anchor.bridge_manager=Manager(root,QtCore.QTimer(anchor));app.setProperty(ANCHOR_KEY,anchor);setattr(app,ANCHOR_KEY+"_keepalive",anchor)
    if not isinstance(anchor,QtCore.QObject) or not shiboken6.isValid(anchor):raise RuntimeError("Invalid existing bridge Qt anchor")
    manager=getattr(anchor,"bridge_manager",None)
    if getattr(manager,"version",None)!=1 or not shiboken6.isValid(manager.timer):raise RuntimeError("Existing bridge manager/timer invalid")
    observed=app.property(ANCHOR_KEY)
    if not isinstance(observed,QtCore.QObject) or not shiboken6.isValid(observed) or getattr(observed,"bridge_manager",None) is not manager:raise RuntimeError("Qt anchor did not preserve its manager; refusing a second timer")
    if root is not None and manager.root!=Path(root).resolve():raise RuntimeError("Another root is anchored in this QApplication")
    return manager

def start(root):
    """Explicit manual compatibility API: one hour/128 requests, no renewal."""
    root=Path(root).resolve();script=root/"tests/designer_smoke.py"
    if not script.is_file() or not script.resolve().is_relative_to(root):raise ValueError("Not a Physics Scatter development project")
    manager=_manager(root,create=True);manager.begin(False,explicit=True);return manager.queue

def ensure_auto():
    """Plugin initialization only; never clears stop/unload latch."""
    manager=None
    try:
        manager=_manager(development_root(),create=True);return manager.begin(True)
    except HOST_ERRORS:
        message=traceback.format_exc()
        if manager is not None:manager.error=message
        warnings.warn("Physics Scatter automatic bridge unavailable: "+message,RuntimeWarning)
        return dict(status="error",error=message,automatic_start_failed=True)

def resume_auto(root=None):
    """Explicit bootstrap/recovery; not a file-request operation."""
    root=development_root() if root is None else Path(root).resolve();script=root/"tests/designer_smoke.py"
    if not script.is_file() or not script.resolve().is_relative_to(root):raise ValueError("Not a Physics Scatter development project")
    return _manager(root,create=True).begin(True,explicit=True)

def status():
    manager=_manager()
    return dict(status="inactive",qt_validated=True) if manager is None else dict(manager.view(),qt_validated=True,timer_active=manager.timer.isActive())

def stop(reason="explicit_stop"):
    manager=_manager()
    if manager is not None:manager.stop(reason)
