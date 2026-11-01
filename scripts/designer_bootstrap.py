"""Stable UI entry point: every Run reads the latest smoke script from disk."""
from pathlib import Path
_scatter_script = Path("D:/Git/SubstancePhysicsScatter/tests/designer_smoke.py")
exec(compile(_scatter_script.read_text(encoding="utf-8"), str(_scatter_script), "exec"), {"__file__": str(_scatter_script), "__name__": "__main__"})
