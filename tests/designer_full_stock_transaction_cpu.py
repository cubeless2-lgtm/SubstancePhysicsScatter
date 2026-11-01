"""Fixed original433 full synchronous transaction affinity control; no SDK here."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_full_stock_reference.py')),run_name='__main__',init_globals={'FX_FIXTURE_MODE':'original','TRANSACTION_CPU':True})
REPORT=_result['REPORT']
