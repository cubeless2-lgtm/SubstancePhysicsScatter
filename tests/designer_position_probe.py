"""Fixed branchoffset-only lane; the original patternsize mode remains default."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_function_binding_probe.py')),run_name='__main__',init_globals={'PROBE_MODE':'branchoffset'})
REPORT=_result['REPORT']
