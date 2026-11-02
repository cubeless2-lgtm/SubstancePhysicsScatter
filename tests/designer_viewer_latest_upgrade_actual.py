"""Install settings entry and refresh slots on the existing idle Designer panel."""
from pathlib import Path
import copy,importlib,json,runpy,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/viewer-latest-upgrade'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json';report={'status':'FAIL','work':str(WORK)}
try:
 import shiboken6
 from substance_physics_scatter import ui,lifecycle,designer,panel_upgrade,viewer_settings,viewer_runtime,viewer_identity
 state=lifecycle.qt_registry();panel=state.get('panel')
 if panel is None or not shiboken6.isValid(panel) or state.get('phase') not in ('ready','hidden'):raise ValueError('Canonical panel is unavailable or not idle')
 snapshot=runpy.run_path(str(ROOT/'tests/designer_prepare_graph_review.py'),run_name='_latest_upgrade_snapshot')['panel_snapshot']
 before=snapshot(panel);target=copy.deepcopy(panel._target_identity);metadata=copy.deepcopy(designer.settings(panel.graph)) if panel.graph is not None else None
 pointer=shiboken6.getCppPointer(panel)[0];dock=shiboken6.getCppPointer(state['dock'])[0]
 widgets={name:shiboken6.getCppPointer(getattr(panel,name))[0] for name in ('viewer_open','viewer_check','viewer_apply','viewer_graph_run','viewer_graph_cancel')}
 presentation=state.get('presentation');before_separate=getattr(presentation,'separate',None);before_visible=panel.isVisible();before_parent=panel.parentWidget()
 for module in (viewer_identity,viewer_runtime,viewer_settings,ui,panel_upgrade):importlib.reload(module)
 added=panel_upgrade.upgrade_latest(panel,ui.Panel)
 for name in tuple(dict.fromkeys(panel_upgrade.METHODS+panel_upgrade.GRAPH_METHODS)):
  if getattr(panel,name).__func__ is not getattr(ui.Panel,name):raise ValueError('Method binding did not refresh: '+name)
 if state.get('panel') is not panel or shiboken6.getCppPointer(panel)[0]!=pointer or shiboken6.getCppPointer(state['dock'])[0]!=dock:raise ValueError('Canonical panel or dock changed')
 if any(shiboken6.getCppPointer(getattr(panel,name))[0]!=pointer_ for name,pointer_ in widgets.items()):raise ValueError('Existing viewer widget changed')
 if panel.parentWidget() is not before_parent or panel.isVisible()!=before_visible or getattr(presentation,'separate',None)!=before_separate:raise ValueError('Panel presentation changed')
 if panel._target_identity!=target or snapshot(panel)!=before:raise ValueError('Existing panel settings changed')
 if panel.graph is not None and designer.settings(panel.graph)!=metadata:raise ValueError('Existing graph metadata changed')
 if not panel.viewer_settings.isEnabled():raise ValueError('Viewer settings entry is disabled')
 report.update(status='PASS',added=added,panel_pointer=pointer,dock_pointer=dock,old_widgets_preserved=True,settings_entry_enabled=True,methods_rebound=True,settings_preserved=True,graph_metadata_preserved=True,presentation_preserved=True)
except BaseException:report['traceback']=traceback.format_exc()
REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
