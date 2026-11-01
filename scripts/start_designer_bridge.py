"""Explicit one-time bootstrap/resume inside Designer; disk edits alone cannot load it."""
from pathlib import Path
import sys
import importlib
_scatter_candidates=[]
if "__file__" in globals():_scatter_candidates.append(Path(__file__).resolve().parents[1])
_scatter_package=sys.modules.get("substance_physics_scatter")
if _scatter_package is not None and getattr(_scatter_package,"__file__",None):_scatter_candidates.append(Path(_scatter_package.__file__).resolve().parents[2])
_scatter_roots={p for p in _scatter_candidates if (p/"scripts/start_designer_bridge.py").is_file() and (p/"plugin/substance_physics_scatter/bridge.py").is_file()}
if len(_scatter_roots)!=1:raise RuntimeError("Open/run the saved start_designer_bridge.py from the development checkout; project root is ambiguous/unavailable")
_scatter_root=_scatter_roots.pop()
sys.path.insert(0,str(_scatter_root/"plugin"))
from substance_physics_scatter import bridge
if getattr(getattr(bridge,"_queue",None),"busy",False):raise RuntimeError("Bridge handler is executing; do not reload it")
if callable(getattr(bridge,"status",None)) and bridge.status().get("busy"):raise RuntimeError("Bridge handler is executing; do not reload it")
bridge.stop()
importlib.reload(bridge)
_scatter_bridge_status=bridge.resume_auto(_scatter_root)
print("Physics Scatter managed bridge: "+str(_scatter_bridge_status))
