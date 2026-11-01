"""Fixed last-owner patternNone + literal zero offset; root owns actual SDK."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_full_stock_reference.py')),run_name='__main__',init_globals={'FX_FIXTURE_MODE':'last_owner_none_zero_offset'})
REPORT=_result['REPORT']
