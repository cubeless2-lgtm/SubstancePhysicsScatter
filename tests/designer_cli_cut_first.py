"""Fixed startup-script check; never drives or closes an existing Designer process."""
from pathlib import Path
import json
import os
import runpy
import traceback

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'output/designer_bridge/bootstrap/cut-first-startup.json'
REPORT.parent.mkdir(parents=True, exist_ok=True)
result = {'pid': os.getpid(), 'status': 'running', 'computer_use': False,
          'context': 'New isolated Designer process, --startup-script and --quit; existing user processes untouched',
          'tolerance': 0}
def write():
    temporary = REPORT.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2), encoding='utf8')
    temporary.replace(REPORT)
write()
try:
    import sd
    from sd.api.apiexception import APIException
    result['designer_version'] = sd.getContext().getSDApplication().getVersion()
    try:
        actual = runpy.run_path(str(ROOT / 'tests/designer_full_stock_cut_first.py'), run_name='__main__')
        report = Path(actual['REPORT'])
        observation = json.loads(report.read_text(encoding='utf8'))
        result.update(status='observation_complete', report=str(report),
                      math_pass=observation.get('math_pass'),
                      observation_status=observation.get('status'))
    except (Exception, APIException):
        result.update(status='error', traceback=traceback.format_exc())
except Exception:
    result.update(status='error', traceback=traceback.format_exc())
write()
