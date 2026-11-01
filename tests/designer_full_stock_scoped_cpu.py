"""Fixed original433 control: affinity is restricted only inside graph.compute."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name('designer_full_stock_reference.py')),run_name='__main__',init_globals={'FX_FIXTURE_MODE':'original','SCOPED_CPU':True})
REPORT=_result['REPORT']
