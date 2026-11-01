"""Designer plugin entry points; importable without Designer for core unit tests."""
_panel = None
_dock = None
_bridge_status = None

def initializeSDPlugin():
    global _panel, _dock, _bridge_status
    from .ui import Panel
    from .designer import application
    from .lifecycle import Session,QtHost,qt_registry
    state=qt_registry()
    def synchronize():
        global _panel,_dock
        _panel=state.get("panel");_dock=state.get("dock")
    session=Session(state,QtHost(Panel,application().getQtForPythonUIMgr()),synchronize)
    try:session.initialize()
    finally:synchronize()
    from .bridge import ensure_auto
    _bridge_status=ensure_auto()

def uninitializeSDPlugin():
    global _panel,_dock,_bridge_status
    from . import bridge
    from .errors import HOST_ERRORS
    try:bridge.stop("plugin_unload")
    except HOST_ERRORS as error:
        import warnings
        _bridge_status={"status":"error","error":str(error),"reason":"plugin_unload"}
        warnings.warn("Physics Scatter bridge stop failed: "+str(error),RuntimeWarning)
    from .ui import Panel
    from .designer import application
    from .lifecycle import Session,QtHost,qt_registry
    state=qt_registry()
    def synchronize():
        global _panel,_dock
        _panel=state.get("panel");_dock=state.get("dock")
    session=Session(state,QtHost(Panel,application().getQtForPythonUIMgr()),synchronize)
    try:session.shutdown()
    finally:synchronize()
