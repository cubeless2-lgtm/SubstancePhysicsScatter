"""Stable allowlisted smoke entry; always reads the latest acceptance lane from disk."""
from pathlib import Path
import runpy
_lane=Path(__file__).resolve().with_name("designer_smoke_routes.py")
_result=runpy.run_path(str(_lane),run_name="__main__")
REPORT=_result["REPORT"]
