"""Submit an allowlisted test request to an already opted-in Designer session."""
from pathlib import Path
import argparse
import json
import os
import time
import uuid
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]

def ready(root,*,now=None):
    root=Path(root).resolve();directory=root/"output/designer_bridge"
    if not directory.resolve().is_relative_to(root):raise ValueError("Bridge directory escapes project")
    for name in ("request.json","processing.json"):
        path=directory/name
        if path.exists() or path.is_symlink():raise ValueError("A request is pending/running; never overwrite or replay it")
    path=directory/"bridge_status.json"
    if not path.is_file() or path.is_symlink() or path.stat().st_size>32768:raise ValueError("No valid status; run start_designer_bridge.py inside Designer once")
    state=json.loads(path.read_text(encoding="utf8"))
    if type(state) is not dict:raise ValueError("Bridge status is not an object")
    if state.get("version")!=2 or not isinstance(state.get("heartbeat_utc"),str):raise ValueError("Legacy bridge has no live heartbeat; run start_designer_bridge.py inside Designer once")
    heartbeat=datetime.fromisoformat(state["heartbeat_utc"])
    if heartbeat.tzinfo is None:raise ValueError("Invalid heartbeat timezone")
    age=((now or datetime.now(timezone.utc))-heartbeat).total_seconds()
    if not -2<=age<=5:raise ValueError("Bridge heartbeat is stale; explicit bootstrap/resume is required")
    if state.get("status")!="listening" or state.get("stop_latched") is not False or state.get("busy") is not False:raise ValueError("Bridge is not ready: "+str(state.get("status"))+" / "+str(state.get("reason")))
    if Path(state.get("root","")).resolve()!=root or type(state.get("pid")) is not int or state["pid"]<=0 or not isinstance(state.get("session"),str) or len(state["session"])!=32:raise ValueError("Bridge owner/session identity differs")
    return state

parser=argparse.ArgumentParser()
parser.add_argument("operation",choices=("health","inspect","smoke","stop","ui_status"))
parser.add_argument("--timeout",type=float,default=120)
args=parser.parse_args()
directory=ROOT/"output/designer_bridge"
try:ready(ROOT)
except (OSError,ValueError,TypeError) as error:raise SystemExit(str(error)) from None
job_id=uuid.uuid4().hex
request=directory/"request.json"
if any(p.exists() or p.is_symlink() for p in (request,directory/"processing.json")):raise SystemExit("A request is pending/running")
# Publish a fully written file atomically; hard-link creation fails if another submitter won.
temporary=directory/("submit_"+job_id+".tmp")
temporary.write_text(json.dumps({"job_id":job_id,"operation":args.operation}),encoding="utf-8")
try:os.link(temporary,request)
finally:temporary.unlink()
response=directory/"responses"/(job_id+".json")
deadline=time.monotonic()+args.timeout
while time.monotonic()<deadline:
    if response.exists():
        result=json.loads(response.read_text(encoding="utf-8"));print(json.dumps(result,indent=2,ensure_ascii=False));raise SystemExit(0 if result["status"]=="completed" else 1)
    time.sleep(.25)
raise SystemExit("No response yet; do not replay the request. Inspect "+str(response))
