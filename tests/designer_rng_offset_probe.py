"""Fixed stock branchoffset RNG restoration; no caller-selected code or paths."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_function_binding_probe.py')),run_name='__main__',init_globals={'PROBE_MODE':'rng_offset'})
REPORT=_result['REPORT']
