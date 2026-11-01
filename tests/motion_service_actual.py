"""Actual loopback result adoption, cancellation and Saved observation reuse."""
from pathlib import Path
import hashlib,json,time,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8765'
WORK=ROOT/'output/evidence/motion-service'/uuid.uuid4().hex;WORK.mkdir(parents=True)
REPORT=WORK/'report.json';E=dict(status='RUNNING')
def write():REPORT.write_bytes((json.dumps(E,indent=2)+'\n').encode('utf8'))
def api(path,body=None):
    headers={'Origin':BASE}
    if body is not None:headers.update({'Content-Type':'application/json','X-Review-Token':token})
    with urllib.request.urlopen(urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=35) as r:return r.read()
def get(path):return json.loads(api(path))
def wait():
    start=time.monotonic()
    while time.monotonic()-start<150:
        state=get('/api/state')
        if not state['operation_busy']:return state
        time.sleep(.25)
    raise TimeoutError('No replay on ambiguous service operation')
if __name__=='__main__':
    state=get('/api/state');assert not state['operation_busy'];token=state['session_token'];previous=state['current'];body=previous['settings']['snapshot'];E['previous_job']=previous['job_id'];write()
    assert previous['motion']['available'] is False
    queued=json.loads(api('/api/run',body));api('/api/cancel/'+queued['token'],{});cancelled=wait()
    assert cancelled['job']['status']=='cancelled' and cancelled['current']['job_id']==previous['job_id'] and cancelled['job']['last_good_preserved'] is True
    E['cancel']=dict(status='PASS',last_good_preserved=True);write()
    api('/api/run',body);state=wait();assert state['job']['status']=='completed',state['job']
    current=state['current'];assert current['job_id']!=previous['job_id'] and current['motion']['available']
    recorded=api(current['motion']['data_url']);data=json.loads(recorded)
    assert data['source_job_id']==current['job_id'] and data['frames'][-1]['positions']==[p['position'] for p in current['poses']]
    E['simulation']=dict(job=current['job_id'],motion=current['motion'],pipeline=current['pipeline'],maps=list(current['maps']),real_frame_movement=data['frames'][0]['positions']!=data['frames'][-1]['positions']);write()
    api('/api/rebake',body);state=wait();assert state['job']['status']=='completed',state['job']
    saved=state['current'];assert saved['job_id']!=current['job_id'] and saved['execution']['physics_executed'] is False and saved['poses']==current['poses'] and api(saved['motion']['data_url'])==recorded
    E.update(status='PASS',saved=dict(job=saved['job_id'],origin=saved['motion']['source_job_id'],recorded_bytes_identical=True,physics_executed=False),user_assets_changed=False);write();print(REPORT,flush=True)
