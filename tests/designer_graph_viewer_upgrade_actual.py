"""Attach Graph/viewer controls to the canonical idle panel, without replacing it."""
from pathlib import Path
import copy,importlib,json,runpy,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/graph-viewer-upgrade'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
report={'status':'FAIL','work':str(WORK)}
try:
 import shiboken6
 from substance_physics_scatter import ui,lifecycle,designer,panel_upgrade
 state=lifecycle.qt_registry();panel=state.get('panel')
 if panel is None or not shiboken6.isValid(panel):raise ValueError('Canonical panel is unavailable')
 if state.get('phase') not in ('ready','hidden'):raise ValueError('Canonical panel lifecycle is not idle')
 snapshot=runpy.run_path(str(ROOT/'tests/designer_prepare_graph_review.py'),run_name='_graph_upgrade_snapshot')['panel_snapshot']
 before=snapshot(panel);target=copy.deepcopy(panel._target_identity)
 metadata=copy.deepcopy(designer.settings(panel.graph)) if panel.graph is not None else None
 pointer=shiboken6.getCppPointer(panel)[0];dock_pointer=shiboken6.getCppPointer(state['dock'])[0]
 presentation=state.get('presentation');before_separate=getattr(presentation,'separate',None)
 before_visible=panel.isVisible();before_parent=panel.parentWidget()
 importlib.reload(ui);importlib.reload(panel_upgrade)
 changed=panel_upgrade.upgrade_graph_viewer(panel,ui.Panel)
 if state.get('panel') is not panel or shiboken6.getCppPointer(panel)[0]!=pointer or shiboken6.getCppPointer(state['dock'])[0]!=dock_pointer:raise ValueError('Canonical panel or native dock changed')
 if panel.parentWidget() is not before_parent or panel.isVisible()!=before_visible or getattr(presentation,'separate',None)!=before_separate:raise ValueError('Panel presentation changed')
 if panel._target_identity!=target or snapshot(panel)!=before:raise ValueError('Existing panel settings changed')
 if panel.graph is not None and designer.settings(panel.graph)!=metadata:raise ValueError('Existing graph metadata changed')
 if not panel.viewer_graph_run.isEnabled() or panel.viewer_graph_cancel.isEnabled():raise ValueError('Graph viewer controls have incorrect idle state')
 if panel_upgrade.upgrade_graph_viewer(panel,ui.Panel):raise ValueError('Upgrade must be idempotent')
 report.update(status='PASS',changed=changed,panel_pointer=pointer,dock_pointer=dock_pointer,settings_preserved=True,graph_metadata_preserved=True,presentation_preserved=True,graph_run_available=True,cancel_disabled_when_idle=True,idempotent=True)
except BaseException:report['traceback']=traceback.format_exc()
REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
