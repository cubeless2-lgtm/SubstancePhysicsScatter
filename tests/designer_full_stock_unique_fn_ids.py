"""Fixed offline function-UID variant; root owns the only actual SDK execution."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_full_stock_reference.py')),run_name='__main__',init_globals={'FX_FIXTURE_MODE':'unique_function_ids'})
REPORT=_result['REPORT']
