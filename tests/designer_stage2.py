"""Stage 2A lane; fixed smoke entry dispatches here without changing the local bridge."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name("designer_acceptance.py")),run_name="__main__",init_globals={"STAGE2":True})
REPORT=_result["REPORT"]
