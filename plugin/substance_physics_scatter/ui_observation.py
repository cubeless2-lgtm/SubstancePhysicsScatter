"""Bounded, getter-only observation of the existing Designer panel registry."""
import math,sys
KEY='substance_physics_scatter_session_v1'

def observe(app,*,valid,pointer,qobject,qwidget,qprocess,on_ui_thread):
    result=dict(status='unavailable',ui_thread=bool(on_ui_thread),mutations=0,package_calls=0,compute_calls=0)
    if app is None:return dict(result,reason='QApplication is not available')
    if not on_ui_thread:raise RuntimeError('Panel observation requires the existing UI thread')
    if not isinstance(app,qobject) or not valid(app):return dict(result,reason='QApplication wrapper is invalid')
    def ptr(obj):return int(pointer(obj)[0]) if isinstance(obj,qobject) and valid(obj) else None
    def scalar(value):
        if value is None or type(value) in (bool,int):return value
        if type(value) is float and math.isfinite(value):return value
        if type(value) is str:return value[:1000]
        return {'unsupported_type':type(value).__name__}
    def describe(obj):
        row=dict(present=obj is not None,type=type(obj).__name__)
        if obj is None:return row
        row['valid']=isinstance(obj,qobject) and bool(valid(obj))
        if not row['valid']:return row
        row.update(pointer=ptr(obj),object_name=str(obj.objectName())[:160],parent_pointer=ptr(obj.parent()))
        return row
    anchor=app.property(KEY);result['anchor']=describe(anchor)
    if not isinstance(anchor,qobject) or not valid(anchor):return dict(result,reason='Existing anchor is absent or invalid')
    state=getattr(anchor,'scatter_state',None)
    if type(state) is not dict:return dict(result,reason='Existing anchor has no plain registry')
    result.update(status='observed',registry={k:scalar(state.get(k)) for k in ('version','layout_version','generation','phase','failure','native_attempted')})
    for key in ('dock','panel','layout','shutdown_process'):result[key]=describe(state.get(key))
    panel=state.get('panel');dock=state.get('dock');layout=state.get('layout')
    if isinstance(dock,qwidget) and valid(dock):result['dock_existing_layout']=describe(dock.layout())
    if isinstance(layout,qobject) and valid(layout):
        count=layout.count()
        if type(count) is not int or not 0<=count<=16:raise RuntimeError('Panel layout observation exceeds16 items')
        result['layout']['count']=count;result['layout']['items']=[describe(layout.itemAt(i).widget()) for i in range(count)]
    if isinstance(panel,qwidget) and valid(panel):
        process=getattr(panel,'process',None);result['process']=describe(process)
        if isinstance(process,qprocess) and valid(process):
            enum=process.state();result['process'].update(state=int(enum.value),pid=int(process.processId()))
        known=hasattr(panel,'_token') and hasattr(panel,'_phase')
        result['panel']['operation_contract_available']=known
        result['panel']['operation_pending']=getattr(panel,'_token',None) is not None if known else None
        result['panel']['operation_phase']=scalar(getattr(panel,'_phase',None))
        result['panel']['closing']=scalar(getattr(panel,'_closing',None))
        result['panel']['graph_ui_enabled']=scalar(getattr(panel,'_graph_ui_enabled',None))
        result['panel']['lifecycle_stopping']=bool(getattr(panel,'_lifecycle_stopping',False))
    module=sys.modules.get('substance_physics_scatter')
    result['module_panel_pointer']=ptr(getattr(module,'_panel',None))
    again=app.property(KEY)
    if ptr(again)!=ptr(anchor) or getattr(again,'scatter_state',None) is not state:raise RuntimeError('Panel registry changed during read-only observation')
    return result

def current():
    from PySide6 import QtCore,QtWidgets
    import shiboken6
    app=QtWidgets.QApplication.instance()
    return observe(app,valid=shiboken6.isValid,pointer=shiboken6.getCppPointer,qobject=QtCore.QObject,qwidget=QtWidgets.QWidget,qprocess=QtCore.QProcess,on_ui_thread=app is not None and app.thread()==QtCore.QThread.currentThread())
