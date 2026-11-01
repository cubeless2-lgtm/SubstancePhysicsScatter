"""Session state machine. The host dock is borrowed; only plugin children are disposed."""
import uuid
from .errors import HOST_ERRORS

VERSION=1

class Session:
    def __init__(self,state,host,changed=lambda:None):
        self.state=state;self.host=host;self.changed=changed
        if state.get("version",VERSION)!=VERSION:raise RuntimeError("Unsupported panel registry version")
        for key,value in {"version":VERSION,"dock":None,"panel":None,"layout":None,"layout_version":VERSION,"generation":0,"phase":"empty","failure":None,"native_attempted":False,"shutdown_process":None}.items():
            state.setdefault(key,value)

    def _present(self,panel):
        hook=getattr(self.host,'presentation',None)
        if hook is not None:hook(self.state,panel)

    def _show(self):
        presentation=self.state.get('presentation')
        if presentation is not None:presentation.show()
        else:self.host.show(self.state['dock'])

    def initialize(self):
        s=self.state;h=self.host
        if s["failure"]:raise RuntimeError("Panel initialization is latched after failure: "+s["failure"])
        if s["phase"] in ("initializing","stopping"):raise RuntimeError("Panel operation is already in progress")
        if s["dock"] is not None and not h.valid(s["dock"]):
            s["failure"]="SDK dock wrapper is invalid";s["phase"]="failed";self.changed();raise RuntimeError(s["failure"])
        if s["panel"] is not None and h.valid(s["panel"]):
            self._present(s["panel"])
            # Showing a hidden busy panel must not resume/reset its task controls.
            h.show(s["panel"]);self._show();s["phase"]="ready";self.changed();return s["panel"]
        # Invalid wrappers are forgotten without invoking any widget method on them.
        s["panel"]=None;s["phase"]="initializing"
        try:
            if s["dock"] is None:
                if s["native_attempted"]:raise RuntimeError("SDK creation was already attempted")
                s["native_attempted"]=True;s["dock_id"]="substance_physics_scatter_"+uuid.uuid4().hex
                s["dock"]=h.create_dock(s["dock_id"])
                if s["dock"] is None or not h.valid(s["dock"]):raise RuntimeError("SDK returned no valid dock")
            if s["layout_version"]!=VERSION:raise RuntimeError("Unsupported panel layout version")
            if s["layout"] is None or not h.valid(s["layout"]):s["layout"]=h.layout(s["dock"])
            panel=h.create_panel(s["dock"]);s["panel"]=panel
            s["generation"]+=1;h.attach(s["layout"],panel)
            self._present(panel)
            h.enable(panel,True);h.show(panel);self._show();s["phase"]="ready";self.changed();return panel
        except HOST_ERRORS as error:
            s["failure"]=repr(error);s["phase"]="failed";self.changed();raise

    def hide(self):
        s=self.state
        if s.get('presentation') is not None:s['presentation'].hide()
        elif s["dock"] is not None and self.host.valid(s["dock"]):self.host.hide(s["dock"])
        if s["phase"]=="ready":s["phase"]="hidden"
        self.changed()

    def shutdown(self):
        s=self.state;h=self.host;self.hide()
        if s["phase"]=="stopping":return
        panel=s["panel"]
        if panel is None or not h.valid(panel):s["panel"]=None;self.changed();return
        s["phase"]="stopping";h.enable(panel,False)
        generation=s["generation"];process=h.process(panel);s["shutdown_process"]=process
        def finished(*_):
            if s["phase"]!="stopping" or s["generation"]!=generation or s["panel"] is not panel or s["shutdown_process"] is not process:return
            # A queued old callback never touches a replacement panel or a different generation.
            if h.valid(panel):
                h.clear_process(panel)
                if s.get('presentation') is not None:s['presentation'].detach(panel)
                h.dispose_child(s["layout"],panel)
            s["panel"]=None;s["shutdown_process"]=None;s["phase"]="hidden";self.changed()
        # New panels acknowledge both synchronous SDK return and any queued
        # continuation, even when there is no QProcess to wait for yet.
        shutdown=getattr(h,'shutdown_panel',None)
        if shutdown is not None and shutdown(panel,finished):
            self.changed();return
        if process is None or not h.valid(process):
            finished();return
        h.on_finished(process,finished)
        h.cancel(panel)
        # Handle an already finished process without blocking the UI or missing its signal.
        if h.finished(process):h.defer(finished)
        self.changed()

class QtHost:
    def __init__(self,panel_factory,ui_manager):self.panel_factory=panel_factory;self.ui_manager=ui_manager
    @staticmethod
    def valid(value):
        import shiboken6
        return value is not None and shiboken6.isValid(value)
    def presentation(self,state,panel):
        from .windowing import Presentation
        controller=state.get('presentation')
        if controller is None:
            controller=Presentation(state,state['dock'],state['layout'])
            state['presentation']=controller
        elif not self.valid(controller) or not self.valid(controller.native):
            raise RuntimeError('Existing presentation wrapper is invalid')
        controller.attach(panel)

    def create_dock(self,identifier):return self.ui_manager.newDockWidget(identifier,"Physics Scatter")
    def create_panel(self,dock):return self.panel_factory(dock)
    @staticmethod
    def layout(dock):
        from PySide6 import QtWidgets
        existing=dock.layout()
        return existing if existing is not None else QtWidgets.QVBoxLayout(dock)
    @staticmethod
    def attach(layout,panel):layout.addWidget(panel)
    @staticmethod
    def enable(panel,enabled):
        if enabled and callable(getattr(panel,'resume',None)):panel.resume()
        panel._lifecycle_stopping=not enabled;panel.setEnabled(enabled)
    @staticmethod
    def show(widget):widget.show()
    @staticmethod
    def hide(widget):widget.hide()
    @staticmethod
    def process(panel):return panel.process
    @staticmethod
    def on_finished(process,callback):process.finished.connect(callback)
    @staticmethod
    def cancel(panel):panel.stop()
    @staticmethod
    def shutdown_panel(panel,callback):
        method=getattr(panel,'request_shutdown',None)
        if not callable(method):return False
        method(callback);return True
    @staticmethod
    def clear_process(panel):
        panel.process=None
    @staticmethod
    def finished(process):
        from PySide6 import QtCore
        return process.state()==QtCore.QProcess.ProcessState.NotRunning
    @staticmethod
    def defer(callback):
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(0,callback)
    @staticmethod
    def dispose_child(layout,panel):
        import shiboken6
        if layout is not None and shiboken6.isValid(layout):layout.removeWidget(panel)
        panel.setParent(None);panel.close();panel.deleteLater()

def qt_registry():
    """Keep a QObject anchor in QApplication so plugin module reload cannot lose the dock."""
    from PySide6 import QtCore,QtWidgets
    import shiboken6
    app=QtWidgets.QApplication.instance()
    if app is None:raise RuntimeError("Designer QApplication is not available")
    key="substance_physics_scatter_session_v1"
    anchor=app.property(key)
    if anchor is None:
        anchor=QtCore.QObject(app);anchor.setObjectName(key);anchor.scatter_state={"version":VERSION}
        app.setProperty(key,anchor)
        # Strong Python reference preserves the anchor's Python state attribute too.
        setattr(app,key+"_keepalive",anchor)
    elif not isinstance(anchor,QtCore.QObject) or not shiboken6.isValid(anchor):
        raise RuntimeError("Invalid existing panel session registry")
    state=getattr(anchor,"scatter_state",None)
    if not isinstance(state,dict):raise RuntimeError("Panel registry state is unavailable; refusing another native dock creation")
    observed=app.property(key)
    if not isinstance(observed,QtCore.QObject) or not shiboken6.isValid(observed) or getattr(observed,"scatter_state",None) is not state:
        raise RuntimeError("Qt registry did not preserve its state; no native dock will be created")
    return state
