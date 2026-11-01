"""Apply presentation to the existing idle Panel; native dock/panel creation forbidden."""
from pathlib import Path
import copy,hashlib,importlib,json,runpy,uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/window-apply'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
E=dict(status='scheduled',native_creations=0,panel_creations=0,worker=0,compute=0)
def publish():REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
publish()
import substance_physics_scatter as scatter
from substance_physics_scatter import lifecycle,ui,windowing
from substance_physics_scatter.errors import HOST_ERRORS
from PySide6 import QtCore,QtWidgets
import shiboken6,sd
snapshot=runpy.run_path(str(ROOT/'tests/designer_prepare_graph_review.py'),run_name='_window_snapshot')['panel_snapshot']
state=lifecycle.qt_registry();panel=state.get('panel');body=state.get('dock')
if panel is None or panel._token is not None or panel.process is not None or panel._phase!='idle':raise ValueError('Canonical panel must be idle')
before=snapshot(panel);pointer=shiboken6.getCppPointer(panel)[0];generation=state['generation']
app=sd.getContext().getSDApplication();current=panel.jobs.current['job_id']
try:
    importlib.reload(windowing)
    previous=state.get('presentation')
    if previous is not None and not hasattr(previous,'window'):
        previous.detach(panel)
        for widget in (previous.toolbar,previous.scroll):
            state['layout'].removeWidget(widget);widget.hide()
        replacement=None
        try:
            replacement=windowing.Presentation(state,body,state['layout']);replacement.attach(panel)
        except BaseException:
            if replacement is not None:
                replacement.native.removeEventFilter(replacement)
                if replacement.scroll.widget() is panel:replacement.detach(panel)
                replacement.window.deleteLater();replacement.toolbar.deleteLater();replacement.scroll.deleteLater();replacement.deleteLater()
            previous.attach(panel)
            raise
        state['presentation']=replacement
        previous.native.removeEventFilter(previous)
        previous.toolbar.deleteLater();previous.scroll.deleteLater();previous.deleteLater()
    importlib.reload(lifecycle)
    session=lifecycle.Session(state,lifecycle.QtHost(ui.Panel,app.getQtForPythonUIMgr()))
    with patch.object(lifecycle.QtHost,'create_dock',side_effect=RuntimeError('No native dock creation allowed')),patch.object(lifecycle.QtHost,'create_panel',side_effect=RuntimeError('No Panel replacement allowed')):
        session.initialize()
    presentation=state['presentation'];native=presentation.native
    def finish():
        try:
            if snapshot(panel)!=before or shiboken6.getCppPointer(panel)[0]!=pointer or state['generation']!=generation or panel.jobs.current['job_id']!=current:raise ValueError('Panel settings/current/identity changed')
            associated=[]
            for obj in native.toggleViewAction().associatedObjects():
                associated.append(dict(class_name=obj.metaObject().className(),name=obj.objectName(),title=obj.title() if isinstance(obj,QtWidgets.QMenu) else ''))
            E.update(status='PASS',panel_pointer=pointer,generation=generation,current=current,panel_settings_unchanged=True,native_pointer=shiboken6.getCppPointer(native)[0],features=native.features().value,allowed_areas=native.allowedAreas().value,floating=native.isFloating(),minimum=[native.minimumWidth(),native.minimumHeight()],body_layout_count=state['layout'].count(),scroll_panel_same=presentation.scroll.widget() is panel,toggle_action_associations=associated)
        except BaseException:
            import traceback
            E.update(status='FAILED',traceback=traceback.format_exc())
        publish()
    QtCore.QTimer.singleShot(100,finish)
except BaseException:
    import traceback
    E.update(status='FAILED',traceback=traceback.format_exc());publish()
