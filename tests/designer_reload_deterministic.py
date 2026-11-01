"""Fixed idle-only reload of the deterministic capture modules. No UI rebuild."""
from pathlib import Path
import importlib,json,traceback,uuid
from substance_physics_scatter.ui_observation import current
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/deterministic-reload'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False);REPORT=WORK/'report.json'
result=dict(status='running',SDK_compute=0,CLI=0,package_mutations=0,computer_use=False)
try:
    before=current();panel=before.get('panel',{})
    if before.get('status')!='observed' or not before.get('ui_thread') or not panel.get('operation_contract_available') or panel.get('operation_pending') or panel.get('operation_phase')!='idle' or panel.get('closing') or panel.get('lifecycle_stopping'):raise ValueError('Canonical panel must be idle')
    if any(before.get(k,{}).get('present') is not False for k in ('process','shutdown_process')):raise ValueError('User process present')
    modules=['mask_source','graph_companion','core','deterministic_renderer','terminal_capture','designer']
    for name in modules:importlib.reload(importlib.import_module('substance_physics_scatter.'+name))
    after=current()
    if after!=before:raise ValueError('Canonical UI state changed during code reload')
    result.update(status='PASS',before=before,after=after,modules=modules)
except BaseException:result.update(status='FAILED',traceback=traceback.format_exc())
REPORT.write_bytes((json.dumps(result,indent=2)+'\n').encode('utf8'))
