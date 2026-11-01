"""Show current source in the existing idle dock; no package/worker mutations."""
from pathlib import Path
import importlib
import json
import uuid
import shiboken6
from PySide6 import QtWidgets
import substance_physics_scatter as plugin

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'output/designer_graph_ui' / ('visible_' + uuid.uuid4().hex)
WORK.mkdir(parents=True, exist_ok=False)
REPORT = WORK / 'report.json'
app = QtWidgets.QApplication.instance()
anchor = app.property('substance_physics_scatter_session_v1')
if anchor is None or not shiboken6.isValid(anchor):
    raise RuntimeError('Existing registry is required; native dock creation is forbidden')
state = anchor.scatter_state
if (state.get('panel') is not None or state.get('shutdown_process') is not None
        or state.get('phase') != 'hidden' or state.get('failure')
        or not shiboken6.isValid(state['dock']) or not shiboken6.isValid(state['layout'])
        or state['layout'].count() != 0 or plugin._panel is not None):
    raise RuntimeError('An idle empty existing dock is required; nothing was reloaded')
pointer = shiboken6.getCppPointer(state['dock'])[0]
for name in ('errors', 'fileio', 'mask_source', 'maskio', 'graph_registry', 'compat',
             'graph_companion', 'core', 'connections', 'terminal_capture', 'designer',
             'lifecycle', 'ui'):
    importlib.reload(importlib.import_module('substance_physics_scatter.' + name))
plugin.initializeSDPlugin()
panel = plugin._panel
panel.refresh_sources()
assert state['panel'] is panel and state['layout'].count() == 1
assert shiboken6.getCppPointer(state['dock'])[0] == pointer
assert panel._graph_ui_enabled and panel.source_inspect.isVisible()
assert panel.process is None and panel._token is None
image = WORK / 'graph-ui-visible.png'
saved = panel.grab().save(str(image))
result = dict(status='visible', work=str(WORK), dock_root_unchanged=True,
              graph_ui_enabled=panel._graph_ui_enabled, source_count=panel.source_choices.count(),
              compute=0, worker=0, package_mutations=0, status_text=panel.status.text(),
              screenshot=dict(path=str(image), saved=bool(saved)))
REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
