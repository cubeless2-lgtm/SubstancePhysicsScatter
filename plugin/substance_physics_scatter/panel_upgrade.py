"""Attach handoff controls to the existing idle Designer Panel without replacing it."""
import types
from .errors import HOST_ERRORS

METHODS=('local_viewer_url','open_local_viewer','check_local_viewer','open_viewer_settings',
         '_viewer_start_check','_viewer_probe','_viewer_start_or_wait','_viewer_start_finish','apply_viewer_result',
         '_handoff_get','_handoff_state','_handoff_manifest','_handoff_next','_handoff_map',
         '_handoff_confirm','_handoff_failure','_stage_handoff','_select','run','set_busy','stop')

def upgrade(panel, panel_class):
    from PySide6 import QtWidgets
    if getattr(panel,'_viewer_ui_upgrade',False):return False
    if getattr(panel,'_phase',None)!='idle' or getattr(panel,'_token',None) is not None or getattr(panel,'process',None) is not None or getattr(panel,'_closing',False) or getattr(panel,'_lifecycle_stopping',False):
        raise ValueError('Wait for the current panel operation before adding viewer integration')
    layout=panel.layout()
    if not isinstance(layout,QtWidgets.QVBoxLayout) or not isinstance(panel.editable_controls,list):raise ValueError('Existing panel layout is not compatible')
    if any(not callable(getattr(panel_class,name,None)) for name in METHODS):raise ValueError('Viewer integration methods are incomplete')
    names=('viewer_target','viewer_open','viewer_check','viewer_apply','viewer_status')
    if any(hasattr(panel,name) for name in names):raise ValueError('Panel has partial viewer integration; refusing to overwrite')
    sentinel=object();old={name:panel.__dict__.get(name,sentinel) for name in METHODS}
    original_controls=list(panel.editable_controls);widgets=[];cancel_hook=None
    try:
        for name in METHODS:setattr(panel,name,types.MethodType(getattr(panel_class,name),panel))
        target=QtWidgets.QLabel('Designer target: '+(panel.graph.getIdentifier() if panel.graph is not None else 'no scatter selected'),panel)
        target.setWordWrap(True);widgets.append(target);panel.viewer_target=target
        actions=QtWidgets.QWidget(panel);row=QtWidgets.QHBoxLayout(actions);row.setContentsMargins(0,0,0,0);widgets.append(actions)
        panel.viewer_open=QtWidgets.QPushButton('Open local 3D viewer',actions);row.addWidget(panel.viewer_open)
        panel.viewer_check=QtWidgets.QPushButton('Check viewer connection',actions);row.addWidget(panel.viewer_check)
        panel.viewer_apply=QtWidgets.QPushButton('Apply current viewer result to selected Designer graph',panel);widgets.append(panel.viewer_apply)
        panel.viewer_status=QtWidgets.QLabel('Local viewer runs separately. Its assets and results are not automatically applied to the selected Designer graph.',panel)
        panel.viewer_status.setWordWrap(True);widgets.append(panel.viewer_status)
        panel.viewer_open.clicked.connect(panel.open_local_viewer);panel.viewer_check.clicked.connect(panel.check_local_viewer);panel.viewer_apply.clicked.connect(panel.apply_viewer_result)
        # Older Panel versions connected Cancel to a captured bound method. Its
        # original handler marks the token cancelled; this extra hook aborts only
        # our pending Qt network reply and leaves the existing signal intact.
        def abort_handoff():
            token=getattr(panel,'_token',None)
            reply=token.get('handoff_reply') if isinstance(token,dict) else None
            if reply is not None:reply.abort()
        cancel_hook=abort_handoff;panel.cancel.clicked.connect(cancel_hook)
        for offset,widget in enumerate(widgets,1):layout.insertWidget(offset,widget)
        panel.editable_controls.append(panel.viewer_apply)
        panel._viewer_ui_upgrade=True;panel._viewer_upgrade_cancel=cancel_hook
        return True
    except HOST_ERRORS:
        if cancel_hook is not None:
            try:panel.cancel.clicked.disconnect(cancel_hook)
            except (RuntimeError,TypeError):pass
        panel.editable_controls[:]=original_controls
        for widget in widgets:
            layout.removeWidget(widget);widget.setParent(None);widget.deleteLater()
        for name in names:
            if name in panel.__dict__:delattr(panel,name)
        for name,value in old.items():
            if value is sentinel:
                if name in panel.__dict__:delattr(panel,name)
            else:setattr(panel,name,value)
        raise

GRAPH_METHODS=('run_viewer_graph','_viewer_graph_state','_viewer_graph_draft','_viewer_graph_capture',
               '_viewer_graph_upload','_viewer_graph_uploaded','_viewer_graph_post','_viewer_graph_started',
               '_viewer_graph_poll','_viewer_graph_polled','_viewer_graph_cancel','_viewer_graph_cancelled',
               '_viewer_graph_failure','_handoff_failure','_select','_end','_try_shutdown_acks','request_shutdown','stop')

def upgrade_graph_viewer(panel,panel_class):
    """Add the separate Graph capture/run action to an already-upgraded idle panel."""
    from PySide6 import QtWidgets
    if getattr(panel,'_viewer_graph_upgrade',False):return False
    if not getattr(panel,'_viewer_ui_upgrade',False):raise ValueError('Upgrade viewer integration first')
    if getattr(panel,'_phase',None)!='idle' or getattr(panel,'_token',None) is not None or getattr(panel,'process',None) is not None or getattr(panel,'_closing',False) or getattr(panel,'_lifecycle_stopping',False) or getattr(panel,'_viewer_start_state',None) is not None or getattr(panel,'_viewer_reply',None) is not None or getattr(panel,'_viewer_settings_dialog',None) is not None:raise ValueError('Wait for the current panel operation')
    layout=panel.layout()
    if not isinstance(layout,QtWidgets.QVBoxLayout) or layout.indexOf(panel.viewer_apply)<0:raise ValueError('Existing panel layout is not compatible')
    if any(not callable(getattr(panel_class,name,None)) for name in GRAPH_METHODS):raise ValueError('Graph viewer methods are incomplete')
    names=('viewer_graph_run','viewer_graph_cancel','viewer_draft_status')
    if any(hasattr(panel,name) for name in names):raise ValueError('Panel has partial Graph viewer integration')
    sentinel=object();old={name:panel.__dict__.get(name,sentinel) for name in GRAPH_METHODS}
    original_controls=list(panel.editable_controls);widgets=[]
    try:
        for name in GRAPH_METHODS:setattr(panel,name,types.MethodType(getattr(panel_class,name),panel))
        panel.viewer_graph_run=QtWidgets.QPushButton('Capture inspected Graph + run submitted viewer settings',panel);widgets.append(panel.viewer_graph_run)
        panel.viewer_graph_cancel=QtWidgets.QPushButton('Cancel Graph viewer run',panel);widgets.append(panel.viewer_graph_cancel)
        panel.viewer_draft_status=QtWidgets.QLabel('First submit settings in the 3D viewer. Each new simulation recaptures the Graph; Saved rebake reuses its stored mask.',panel);panel.viewer_draft_status.setWordWrap(True);widgets.append(panel.viewer_draft_status)
        panel.viewer_graph_run.clicked.connect(panel.run_viewer_graph);panel.viewer_graph_cancel.clicked.connect(panel.stop);panel.viewer_graph_cancel.setEnabled(False)
        index=layout.indexOf(panel.viewer_apply)+1
        for offset,widget in enumerate(widgets):layout.insertWidget(index+offset,widget)
        panel.editable_controls.append(panel.viewer_graph_run);panel._viewer_graph_upgrade=True
        return True
    except HOST_ERRORS:
        panel.editable_controls[:]=original_controls
        for widget in widgets:layout.removeWidget(widget);widget.setParent(None);widget.deleteLater()
        for name in names:
            if name in panel.__dict__:delattr(panel,name)
        for name,value in old.items():
            if value is sentinel:
                if name in panel.__dict__:delattr(panel,name)
            else:setattr(panel,name,value)
        raise

def refresh_methods(panel,panel_class):
    """Refresh only integration methods and their captured button slots on an idle panel."""
    if not getattr(panel,'_viewer_ui_upgrade',False) or not getattr(panel,'_viewer_graph_upgrade',False):raise ValueError('Both viewer upgrades are required first')
    if getattr(panel,'_phase',None)!='idle' or getattr(panel,'_token',None) is not None or getattr(panel,'process',None) is not None or getattr(panel,'_closing',False) or getattr(panel,'_lifecycle_stopping',False) or getattr(panel,'_viewer_start_state',None) is not None or getattr(panel,'_viewer_reply',None) is not None or getattr(panel,'_viewer_settings_dialog',None) is not None:raise ValueError('Wait for the current panel operation')
    methods=tuple(dict.fromkeys(METHODS+GRAPH_METHODS))
    if any(not callable(getattr(panel_class,name,None)) for name in methods):raise ValueError('Viewer method set is incomplete')
    slots=(('viewer_open','open_local_viewer'),('viewer_check','check_local_viewer'),('viewer_apply','apply_viewer_result'),('viewer_graph_run','run_viewer_graph'),('viewer_graph_cancel','stop'))
    if hasattr(panel,'viewer_settings'):slots+=(('viewer_settings','open_viewer_settings'),)
    for widget,_ in slots:
        if not hasattr(panel,widget):raise ValueError('Viewer control is missing: '+widget)
    sentinel=object();old={name:panel.__dict__.get(name,sentinel) for name in methods}
    old_slots={method:getattr(panel,method) for _,method in slots};disconnected=[];connected=[]
    try:
        # Only detach our exact previously captured slots. Other widget listeners stay intact.
        for widget,method in slots:
            signal=getattr(panel,widget).clicked
            if signal.disconnect(old_slots[method]) is False:raise RuntimeError('Viewer slot was not connected: '+widget)
            disconnected.append((widget,method))
        for name in methods:setattr(panel,name,types.MethodType(getattr(panel_class,name),panel))
        for widget,method in slots:
            bound=getattr(panel,method);getattr(panel,widget).clicked.connect(bound);connected.append((widget,bound))
        return True
    except HOST_ERRORS:
        for widget,bound in reversed(connected):
            try:getattr(panel,widget).clicked.disconnect(bound)
            except (RuntimeError,TypeError):pass
        for name,value in old.items():
            if value is sentinel:
                if name in panel.__dict__:delattr(panel,name)
            else:setattr(panel,name,value)
        for widget,method in disconnected:getattr(panel,widget).clicked.connect(old_slots[method])
        raise

def upgrade_viewer_settings(panel,panel_class):
    """Add the nonmodal settings entry without replacing the existing panel."""
    from PySide6 import QtWidgets
    if hasattr(panel,'viewer_settings'):return False
    if not getattr(panel,'_viewer_ui_upgrade',False) or getattr(panel,'_phase',None)!='idle' or getattr(panel,'_token',None) is not None or getattr(panel,'process',None) is not None or getattr(panel,'_closing',False) or getattr(panel,'_lifecycle_stopping',False):raise ValueError('Wait for the current panel operation')
    layout=panel.layout()
    if not isinstance(layout,QtWidgets.QVBoxLayout) or layout.indexOf(panel.viewer_apply)<0:raise ValueError('Existing panel layout is not compatible')
    sentinel=object();old=panel.__dict__.get('open_viewer_settings',sentinel);button=None
    try:
        panel.open_viewer_settings=types.MethodType(panel_class.open_viewer_settings,panel)
        button=QtWidgets.QPushButton('Set viewer simulation in Designer',panel)
        button.clicked.connect(panel.open_viewer_settings);layout.insertWidget(layout.indexOf(panel.viewer_apply)+1,button)
        panel.viewer_settings=button;panel.editable_controls.append(button)
        return True
    except HOST_ERRORS:
        if button is not None:
            if button in panel.editable_controls:panel.editable_controls.remove(button)
            layout.removeWidget(button);button.setParent(None);button.deleteLater()
        if 'viewer_settings' in panel.__dict__:delattr(panel,'viewer_settings')
        if old is sentinel:
            if 'open_viewer_settings' in panel.__dict__:delattr(panel,'open_viewer_settings')
        else:panel.open_viewer_settings=old
        raise

def upgrade_latest(panel,panel_class):
    """Atomically add the settings entry and refresh integration bindings."""
    if getattr(panel,'_viewer_start_state',None) is not None or getattr(panel,'_viewer_reply',None) is not None or getattr(panel,'_viewer_settings_dialog',None) is not None:raise ValueError('Wait for the current viewer operation')
    sentinel=object();old=panel.__dict__.get('open_viewer_settings',sentinel);controls=list(panel.editable_controls)
    added=upgrade_viewer_settings(panel,panel_class)
    try:
        refresh_methods(panel,panel_class)
    except HOST_ERRORS:
        if added:
            button=panel.viewer_settings;panel.layout().removeWidget(button);button.setParent(None);button.deleteLater();delattr(panel,'viewer_settings')
            panel.editable_controls[:]=controls
            if old is sentinel:
                if 'open_viewer_settings' in panel.__dict__:delattr(panel,'open_viewer_settings')
            else:panel.open_viewer_settings=old
        raise
    return added
