"""Fixed File Mask lane. Only the coordinator may execute this inside Designer."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name("designer_acceptance.py")),run_name="__main__",init_globals={"STAGE2":True,"POSE_COMPAT":True,"FILE_MASK":True})
REPORT=_result["REPORT"]
