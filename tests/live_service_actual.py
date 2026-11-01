"""Root-owned actual LIVE cancellation/failure checks; no input asset edits."""
from pathlib import Path
import json,re,subprocess,sys,time,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8765'
WORK=ROOT/'output/evidence/live-service'/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/'report.json';E=dict(status='RUNNING',cases=[])
def publish():REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
def call(path,body=None):
    headers={'Origin':BASE}
    if body is not None:headers.update({'Content-Type':'application/json','X-Review-Token':TOKEN})
    with urllib.request.urlopen(urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=30) as response:return json.load(response)
def wait_idle():
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        value=call('/api/state')
        if not value['operation_busy']:return value
        time.sleep(.05)
    raise TimeoutError('Owned job cleanup uncertain; never replay')

if __name__=='__main__':
    def failed(kind,value,traceback):
        E.update(status='FAILED',error=str(value));publish();sys.__excepthook__(kind,value,traceback)
    sys.excepthook=failed
    for action in sys.argv[1:] or ('cancel','failure'):
        if action not in ('cancel','failure'):raise ValueError('Fixed actual action required')
        state=call('/api/state');assert not state['operation_busy'];TOKEN=state['session_token']
        previous=state['current'];body=previous['settings']['snapshot']
        current_path=ROOT/'local_review/workspace/jobs/current.json';before=current_path.read_bytes()
        queued=call('/api/run',body);observations=[];sequences=set();started=time.monotonic();active=None
        publish()
        while time.monotonic()-started<30:
            active=call('/api/live-state')
            frame=active.get('frame')
            if active.get('status')=='running' and frame:
                assert active['token']==queued['token'] and frame['job_id']==active['job_id']
                value=call('/api/state')
                assert value['operation_busy'] and value['job']['status']=='running' and value['current']['job_id']==previous['job_id']
                assert not (ROOT/'local_review/workspace/jobs/runs'/active['job_id']/'result.json').exists()
                if frame['sequence'] not in sequences:
                    sequences.add(frame['sequence']);observations.append(frame)
                if len(observations)>=3 and observations[0]['positions']!=observations[-1]['positions']:break
            if active.get('token')==queued['token'] and active.get('status') in ('failed','cancelled','error'):raise ValueError(active)
            time.sleep(.033)
        else:raise TimeoutError('No moving actual frames before result')
        if action=='cancel':call('/api/cancel/'+queued['token'],{})
        else:
            # Kill only the exact active job's private child after proving its command line.
            pid=frame['process_id'];job=active['job_id'];assert type(pid) is int and pid>0 and re.fullmatch('[0-9a-f]{32}',job)
            command="$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(pid)+"'; if ($p.CommandLine -like '*SubstancePhysicsScatter*scatter_worker_periodic_live.exe*"+job+"*request.json*') { Stop-Process -Id "+str(pid)+" } else { throw 'Owned live child identity differs' }"
            killed=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            assert killed.returncode==0,killed.stderr.decode('utf8',errors='replace')
        after=wait_idle();expected='cancelled' if action=='cancel' else 'failed'
        assert after['job']['status']==expected and after['job']['last_good_preserved'] is True and after['current']['job_id']==previous['job_id'] and current_path.read_bytes()==before
        final_live=call('/api/live-state');assert final_live.get('status') not in ('starting','running','baking')
        (WORK/(action+'-running-frames.json')).write_bytes(json.dumps(observations,indent=2).encode())
        E['cases'].append(dict(action=action,status='PASS',job=active['job_id'],moving_frames_before_result=len(observations),last_good=previous['job_id'],current_bytes_preserved=True,terminal_status=after['job']['status'],live_terminal=final_live.get('status')));publish();print(action,'PASS',flush=True)
    E['status']='PASS';publish();print(REPORT,flush=True)
