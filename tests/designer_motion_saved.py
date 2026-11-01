"""Closed Saved-only lane sharing the current-settings actual verifier."""
from pathlib import Path
scope={'__file__':str(Path(__file__).with_name('designer_motion_actual.py')),'__name__':'__main__','SAVED':True}
exec(compile(Path(scope['__file__']).read_text(encoding='utf8'),scope['__file__'],'exec'),scope)
REPORT=scope['REPORT']
