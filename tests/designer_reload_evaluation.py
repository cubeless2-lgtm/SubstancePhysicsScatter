"""Fixed idle-only development reload; never creates/disposes a dock or package."""
from pathlib import Path
import importlib,json,uuid,traceback
from substance_physics_scatter.errors import HOST_ERRORS
from substance_physics_scatter.ui_observation import current

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/evaluation-reload'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json'
result=dict(status='running',compute=0,package_mutations=0,computer_use=False)
try:
    before=current()
    if before.get('status')!='observed' or not before.get('ui_thread'):raise ValueError('Designer UI observation required')
    if before.get('registry',{}).get('failure') is not None:raise ValueError('Existing registry failure')
    panel=before.get('panel',{})
    if not panel.get('operation_contract_available') or panel.get('operation_pending') or panel.get('operation_phase')!='idle' or panel.get('closing') or panel.get('lifecycle_stopping'):raise ValueError('Canonical panel is not idle')
    if any(before.get(k,{}).get('present') is not False for k in ('process','shutdown_process')):raise ValueError('User process present or unobserved')
    result['before']=before
    for name in ('evaluation','terminal_capture','designer'):
        module=importlib.import_module('substance_physics_scatter.'+name)
        importlib.reload(module)
    from substance_physics_scatter import evaluation,designer
    if not callable(getattr(evaluation,'evaluation_scope',None)) or designer.compute_graph is not evaluation.compute_graph:raise ValueError('New evaluation code not active')
    after=current()
    if after!=before:raise ValueError('Canonical UI ownership/state changed during module reload')
    result.update(status='pass',after=after,modules=['evaluation','terminal_capture','designer'])
except HOST_ERRORS:
    result.update(status='error',traceback=traceback.format_exc())
temp=REPORT.with_suffix('.tmp');temp.write_text(json.dumps(result,indent=2),encoding='utf8');temp.replace(REPORT)
