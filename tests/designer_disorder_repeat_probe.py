"""Fixed source Disorder0→50→0 with one lowest-parent stock function restored."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_function_binding_probe.py')),run_name='__main__',init_globals={'PROBE_MODE':'disorder_repeat'})
REPORT=_result['REPORT']
