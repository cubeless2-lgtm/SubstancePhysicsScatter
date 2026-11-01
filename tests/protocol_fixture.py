"""Well-formed synthetic pose protocol fixture; never presented as a physics-engine run."""
import copy
import json
from substance_physics_scatter import compat
from substance_physics_scatter.core import atomic_json,VERSION,digest

def synthetic_current(jobs,path,poses,physics_contract=1):
    request=json.loads(path.read_text(encoding="utf-8"));directory=path.parent
    # This deliberately synthetic historical producer is format1, not an executed Mask physics2 run.
    physical_path=directory/"physics_inputs.json";original=physical_path.read_bytes();physical=json.loads(original)
    physical["physics_input_format_version"]=1;physical.pop("scatter_mask",None)
    physical_path.write_bytes(json.dumps(physical,separators=(",",":") if b': ' not in original else None).encode())
    request.update(worker_version="synthetic-protocol-fixture",physics_input_format_version=1,bake_contract_version=1,scatter_mask=None,physics_input_hash=digest(physical_path))
    request["physics_contract_version"]=physics_contract
    request["simulation_key"]=compat.simulation_key(request["physics_input_hash"],physics_contract)
    atomic_json(path,request)
    record=dict(job_id=request["job_id"],worker_version=request["worker_version"],pose_format_version=1,physics_contract_version=physics_contract,physics_input_format_version=1,
                key_scheme="physics_input_v1",simulation_key=request["simulation_key"],physics_input_hash=request["physics_input_hash"],
                poses=copy.deepcopy(poses),steps=0,settling_status="synthetic_protocol_fixture",**compat.SEMANTICS)
    atomic_json(directory/"origin_result.json",record);raw_sha=digest(directory/"origin_result.json")
    origin=dict(job_id=request["job_id"],worker_version=request["worker_version"],physics_contract_version=physics_contract,record_sha256=raw_sha)
    result=dict(request,poses=copy.deepcopy(poses),source_steps=0,steps=0,settling_status=record["settling_status"],pose_origin=origin,
                origin=dict(record_path="origin_result.json",record_sha256=raw_sha,kind="origin_result"),
                execution=dict(physics_executed=True,body_count=len(poses),steps=0),status="completed")
    result["pose_envelope"]=dict(pose_format_version=1,physics_input_hash=request["physics_input_hash"],key_scheme="physics_input_v1",simulation_key=request["simulation_key"],poses=copy.deepcopy(poses),origin=origin,**compat.SEMANTICS)
    atomic_json(directory/"result.json",result)
    atomic_json(jobs.directory/"current.json",dict(job_id=request["job_id"],request=request,result=result,result_path=str(directory/"result.json"),simulation_key=request["simulation_key"],files={}))
    return directory/"result.json"
