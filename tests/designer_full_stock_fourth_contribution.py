"""Two closed last-owner arms; exact baseline skips the None arm. Root-only SDK."""
from pathlib import Path
import hashlib,json,runpy,traceback,uuid
ROOT=Path(__file__).resolve().parents[1]
DRIVER=ROOT/'tests/designer_full_stock_reference.py'

def completed_arm(value):
    if value.get('status')!='full_stock_reference_observation_complete':return False
    if any(value.get(k) is not True for k in ('inventory_unchanged','user_unchanged','original_disks_unchanged')):return False
    if value.get('raw_count')!=7 or value.get('raw_bytes')!=3670016 or value.get('driver_source',{}).get('unchanged') is not True:return False
    counts=value.get('counts',{});ledger=value.get('ledger',{})
    if any(counts.get(k)!=n for k,n in (('compute',3),('disorder_set',3),('new_package',1),('save',1))):return False
    if ledger.get('ambiguous') is not False or ledger.get('load_calls')!=1 or ledger.get('final_unload_calls')!=2:return False
    owned=ledger.get('owned',[])
    return len(owned)==2 and all(r.get('state')=='removed' for r in owned) and type(value.get('return_comparison',{}).get('exact')) is bool and 'loaded_function_metadata' in value

def next_arm(value):
    if not completed_arm(value):return dict(run_control=False,reason='baseline_incomplete_or_protection_unverified')
    if value['return_comparison']['exact']:return dict(run_control=False,reason='baseline_return_exact0')
    return dict(run_control=True,reason='baseline_return_mismatch_preserved')

def main():
    work=ROOT/'output/evidence/full-stock-fourth-contribution'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=False);report=work/'summary.json';driver_sha=hashlib.sha256(DRIVER.read_bytes()).hexdigest()
    result=dict(status='running',product_acceptance=False,original_stock_failure_resolved=False,maximum_arms=2,maximum_compute=6,maximum_raw=14,maximum_raw_bytes=7340032,arms=[],driver_sha256=driver_sha,scope='Each arm has a fresh private source context and the same cloned data UID/local function IDs. Raw fixture arms differ only at the cloned pattern token; identical RNG streams, engine sharing/optimization, a single cause and a product correction are not established. Exact baseline skips the control; no failed arm is retried.')
    def write():
        temp=report.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(report)
    def arm(mode):
        if hashlib.sha256(DRIVER.read_bytes()).hexdigest()!=driver_sha:raise ValueError('Driver changed between fixed arms')
        namespace=runpy.run_path(str(DRIVER),run_name='__main__',init_globals={'FX_FIXTURE_MODE':mode});path=Path(namespace['REPORT']);raw=path.read_bytes();value=json.loads(raw)
        result['arms'].append(dict(mode=mode,report=str(path),report_sha256=hashlib.sha256(raw).hexdigest(),return_exact=value.get('return_comparison',{}).get('exact')));write()
        if value.get('driver_source',{}).get('before_sha256')!=driver_sha:raise ValueError('Arm driver identity differs')
        return value
    write()
    try:
        baseline=arm('last_owner_split_baseline');decision=next_arm(baseline);result['decision']=decision;write()
        if decision['run_control']:
            control=arm('last_owner_split_none');result['status']='fourth_gaussian_contribution_observation_complete' if completed_arm(control) else 'failed_control';result['baseline_math_failure_preserved']=True
        else:result['status']='baseline_exact_control_skipped' if decision['reason']=='baseline_return_exact0' else 'failed_baseline_control_skipped'
    except Exception as error:result.update(status='failed',error=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
    finally:
        result['driver_unchanged']=hashlib.sha256(DRIVER.read_bytes()).hexdigest()==driver_sha
        if not result['driver_unchanged']:result['status']='failed_driver_changed'
        write()
    return report

if __name__=='__main__':
    REPORT=main()
    print(str(REPORT))
