"""Read-only Qt parent-chain and size-constraint observation for the canonical panel."""
from pathlib import Path
import json,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/window-inspect'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
import substance_physics_scatter
from substance_physics_scatter.lifecycle import qt_registry
from PySide6 import QtWidgets
import shiboken6
state=qt_registry();panel=state.get('panel')
if panel is None or panel._token is not None or panel.process is not None or panel._phase!='idle':raise ValueError('Canonical panel must be idle')
rows=[];widget=state.get('dock')
for i in range(16):
    if widget is None or not shiboken6.isValid(widget):break
    row=dict(level=i,class_name=widget.metaObject().className(),object_name=widget.objectName(),pointer=shiboken6.getCppPointer(widget)[0])
    if isinstance(widget,QtWidgets.QWidget):
        row.update(is_window=widget.isWindow(),window_title=widget.windowTitle(),minimum=[widget.minimumWidth(),widget.minimumHeight()],maximum=[widget.maximumWidth(),widget.maximumHeight()],geometry=[widget.x(),widget.y(),widget.width(),widget.height()])
    if isinstance(widget,QtWidgets.QDockWidget):row.update(qdock=True,features=widget.features().value,allowed_areas=widget.allowedAreas().value,floating=widget.isFloating())
    rows.append(row);widget=widget.parent()
presentation=state.get('presentation');window=getattr(presentation,'window',None)
extra=None
if window is not None:
    extra=dict(separate=presentation.separate,visible=window.isVisible(),geometry=[window.x(),window.y(),window.width(),window.height()],minimum=[window.minimumWidth(),window.minimumHeight()],maximum=[window.maximumWidth(),window.maximumHeight()],flags=window.windowFlags().value,size_grip=window.isSizeGripEnabled(),layout_min=[presentation.window_layout.minimumSize().width(),presentation.window_layout.minimumSize().height()],panel_in_scroll=presentation.scroll.widget() is panel,current=panel.jobs.current['job_id'])
REPORT.write_text(json.dumps(dict(status='OBSERVED',mutation=0,parent_chain=rows,panel_pointer=shiboken6.getCppPointer(panel)[0],layout_count=state['layout'].count(),presentation=extra),indent=2),encoding='utf8')
