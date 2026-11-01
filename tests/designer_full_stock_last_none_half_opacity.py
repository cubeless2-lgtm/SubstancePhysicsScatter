"""Fixed None/zero-offset last owner with Float4 opacity .5; root-only SDK."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_full_stock_reference.py')),run_name='__main__',init_globals={'FX_FIXTURE_MODE':'last_owner_none_half_opacity'})
REPORT=_result['REPORT']
