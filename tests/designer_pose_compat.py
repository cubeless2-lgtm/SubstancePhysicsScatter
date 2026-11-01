"""Allowlisted 2A.1 actual Designer acceptance; parent alone owns execution."""
from pathlib import Path
import runpy
_result=runpy.run_path(str(Path(__file__).with_name("designer_acceptance.py")),run_name="__main__",init_globals={"STAGE2":True,"POSE_COMPAT":True})
REPORT=_result["REPORT"]
