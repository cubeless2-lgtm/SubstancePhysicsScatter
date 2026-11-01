"""Immutable pose provenance and versioned physics-input protocol (no Designer imports)."""
from pathlib import Path
import copy
import hashlib
import json
import math
import re
from .fileio import io_path,logical_path
from . import maskio

VERSIONS=dict(pose_format_version=1,physics_contract_version=2,bake_contract_version=2,physics_input_format_version=2)
PERIODIC_VERSIONS=dict(pose_format_version=1,physics_contract_version=3,bake_contract_version=3,physics_input_format_version=3)
PERIODIC=dict(domain_axes="XY",representative="com_half_open",render_pose="asset_origin_same_lattice_shift",solver_contract="jolt5_2_periodic_coupled_v1",mask_sampling="initial_center_input2")
SEMANTICS=dict(coordinate_system="RH_Z_UP",units="meters",scale_semantics="final_uniform_scale_on_original_vertices")
NEW_FIELDS=set(VERSIONS)|{"physics_input_hash","pose_envelope","pose_origin","origin","key_scheme","execution","legacy_proof","scale_semantics","source_steps","rebake_source","physics_inputs_path","pose_source_path","pose_source_hash"}
SPAWN_FIELDS=("requested_count","spawned_count","attempt_count","max_attempts","spawn_status","spawn_stop_reason","initial_positions")
NEW_FIELDS.update(SPAWN_FIELDS[:-1]);NEW_FIELDS.add("scatter_mask")
NEW_FIELDS.add("periodic")
LIMIT=16*1024*1024
TOTAL=128*1024*1024
RESIM="저장된 pose의 호환성 또는 원본 이력을 확인할 수 없습니다. Simulate + Bake를 실행하세요."
DEFAULTS=dict(count=40,width=4.,depth=4.,seconds=12.,seed=1,edges="walls",friction=.6,restitution=.05)

def encoded(value):return json.dumps(value,sort_keys=True,allow_nan=False).encode("utf-8")
def sha(data):return hashlib.sha256(data).hexdigest()
def run_id(value):
    if not isinstance(value,str) or not re.fullmatch("[0-9a-f]{32}",value):raise ValueError(RESIM+" Invalid run ID")
    return value
def input_version(version):
    if type(version) is not int or version not in (1,2,3):raise ValueError(RESIM+" Unsupported physics input format")
    return version

def versions_for_input(version):
    input_version(version)
    return dict(PERIODIC_VERSIONS if version==3 else VERSIONS,physics_input_format_version=version)

def periodic_identity(value):
    if type(value) is not dict or set(value)!=set(PERIODIC) or any(type(value[k]) is not str or value[k]!=v for k,v in PERIODIC.items()):raise ValueError(RESIM+" Unsupported periodic policy")
    return dict(PERIODIC)

def simulation(raw,*,version=1):
    input_version(version)
    if not isinstance(raw,dict) or set(raw)-set(DEFAULTS):raise ValueError("Unknown simulation field/global scale")
    result=dict(DEFAULTS);result.update(raw)
    for name,low,high in (("count",1,5000),("seed",0,4294967295),("width",.1,1000),("depth",.1,1000),("seconds",.1,120),("friction",0,2),("restitution",0,1)):
        value=result[name]
        if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError("Invalid simulation "+name)
        if name in ("count","seed"):
            if type(value) is not int:raise ValueError(name+" must be an integer")
        else:result[name]=float(value) if value else 0.
    if version==3:
        if type(result["edges"]) is not str or result["edges"]!="periodic":raise ValueError("Input3 requires periodic edges")
    elif result["edges"] not in ("open","walls"):raise ValueError("Only open/walls are supported without explicit input3")
    return result
def asset_identity(rows):
    result=[];seen=set()
    for row in sorted(rows,key=lambda row:row["asset_id"]):
        identity=row["asset_id"]
        if not re.fullmatch("[0-9a-f]{32}",identity) or identity in seen:raise ValueError("Invalid asset identity")
        seen.add(identity)
        if row["format"]!="obj" or not re.fullmatch("[0-9a-f]{64}",row["content_hash"]):raise ValueError("Invalid asset hash/format")
        values={}
        for name in ("weight","scale"):
            value=row[name]
            if type(value) not in (int,float) or not math.isfinite(value) or value<0 or (name=="scale" and not 0<value<=100):raise ValueError("Invalid asset "+name)
            values[name]=float(value) if value else 0.
        result.append(dict(asset_id=identity,content_hash=row["content_hash"],format="obj",**values))
    if not result:raise ValueError("Empty asset identity")
    return result
def inputs(rows,raw,scatter_mask=None,version=1):
    input_version(version)
    if version==3:
        if type(rows) is not list or not rows or any(type(r) is not dict or any(type(r.get(k)) is not str for k in ("asset_id","content_hash","format")) for r in rows):raise ValueError(RESIM+" Invalid input3 assets")
    result=dict(physics_input_format_version=version,assets=asset_identity(rows),simulation=simulation(raw,version=version))
    if version in (2,3):result["scatter_mask"]=maskio.identity(scatter_mask)
    elif scatter_mask is not None:raise ValueError(RESIM+" Mask change requires simulation")
    if version==3:result["periodic"]=dict(PERIODIC)
    return result

def stored_inputs(wanted,version):
    input_version(version)
    if version!=3 and isinstance(wanted,dict) and "periodic" in wanted:raise ValueError(RESIM+" Periodic metadata requires input3")
    if version==3:
        if type(wanted) is not dict or set(wanted)!={"physics_input_format_version","assets","simulation","scatter_mask","periodic"} or type(wanted["physics_input_format_version"]) is not int or wanted["physics_input_format_version"]!=3:raise ValueError(RESIM+" Input3 physical keys/version")
        periodic_identity(wanted["periodic"])
        if type(wanted["simulation"]) is not dict or set(wanted["simulation"])!=set(DEFAULTS):raise ValueError(RESIM+" Input3 simulation keys")
        if type(wanted["assets"]) is not list or any(type(r) is not dict or set(r)!={"asset_id","content_hash","format","weight","scale"} for r in wanted["assets"]):raise ValueError(RESIM+" Input3 asset keys")
        if wanted["scatter_mask"] is not None and (type(wanted["scatter_mask"]) is not dict or set(wanted["scatter_mask"])!=set(maskio.POLICY)|{"content_hash"}):raise ValueError(RESIM+" Input3 Mask identity keys")
    result=inputs(wanted["assets"],wanted["simulation"],wanted.get("scatter_mask"),version)
    if version==3 and wanted!=result:raise ValueError(RESIM+" Input3 noncanonical semantic identity")
    return result
def simulation_key(input_hash,contract=1):
    if not re.fullmatch("[0-9a-f]{64}",input_hash) or type(contract) is not int or contract<=0:raise ValueError("Invalid key identity")
    return sha(("physics_input_v1\n"+input_hash+"\n"+str(contract)+"\n").encode())
def semantics(record):
    if any(record.get(k)!=v for k,v in SEMANTICS.items()):raise ValueError(RESIM+" Invalid pose semantics")
def formats(record,origin=False):
    periodic=record.get("physics_input_format_version")==3
    for key in VERSIONS:
        if origin and key=="bake_contract_version":continue
        supported=(1,) if key=="pose_format_version" else (3,) if periodic else (1,2)
        if type(record.get(key)) is not int or ((record[key]!=3 if periodic else record[key]<=0) if key=="physics_contract_version" else record[key] not in supported):raise ValueError(RESIM+" Unsupported/partial contract")
    if not isinstance(record.get("worker_version"),str) or not record["worker_version"]:raise ValueError(RESIM+" Missing worker version")
    if "periodic" in record:
        if not periodic:raise ValueError(RESIM+" Periodic metadata requires input3")
        periodic_identity(record["periodic"])
def validate_raw_poses(poses,assets,version=1):
    input_version(version)
    from .core import validate_poses
    validate_poses(poses,assets,allow_empty=version in (2,3))

def spawn_metrics(record,physical,root,initial=False):
    if physical["physics_input_format_version"] not in (2,3):raise ValueError(RESIM+" Spawn metadata requires input2/3")
    for field in SPAWN_FIELDS[:4]:nonnegative_int(record.get(field),field)
    requested=record["requested_count"];spawned=record["spawned_count"];attempt=record["attempt_count"];maximum=record["max_attempts"]
    positions=record["initial_positions"]
    if requested!=physical["simulation"]["count"] or spawned!=len(record["poses"]) or not 0<=spawned<=requested or maximum!=min(50000,requested*10) or not 0<=attempt<=maximum or not isinstance(positions,list) or len(positions)!=spawned:raise ValueError(RESIM+" Spawn counts/positions mismatch")
    for position in positions:
        if not isinstance(position,list) or len(position)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in position):raise ValueError(RESIM+" Invalid initial position")
    status=record["spawn_status"];reason=record["spawn_stop_reason"]
    valid=(status=="complete" and reason=="requested_count_reached" and spawned==requested and requested<=attempt<=maximum)
    valid|=(status==("partial" if spawned else "empty") and spawned<requested and reason=="attempts_exhausted" and attempt==maximum)
    valid|=(status==("partial" if spawned else "empty") and spawned<requested and reason=="initial_height_limit" and 1<=attempt<=maximum)
    valid|=(status=="empty" and reason=="all_black" and spawned==0 and attempt==0)
    if not valid:raise ValueError(RESIM+" Invalid spawn status/reason")
    descriptor=physical["scatter_mask"];black=False
    if descriptor is not None:
        path=maskio.cache_path(root,descriptor["content_hash"]);data,_=maskio.read(path,descriptor["content_hash"]);black=maskio.decode_black(data)
    if black!=(reason=="all_black"):raise ValueError(RESIM+" all-black reason does not match actual Mask")
    origin_metrics(record)
    if spawned==0 and (record["steps"]!=0 or record["settling_status"]!="not_run"):raise ValueError(RESIM+" Empty physics must be not_run/steps0")
    if spawned and record["settling_status"]=="not_run":raise ValueError(RESIM+" Nonempty physics cannot be not_run")
    if initial:
        execution=record.get("execution");expected=dict(physics_executed=spawned>0,body_count=spawned,steps=record["steps"])
        if not isinstance(execution,dict) or type(execution.get("physics_executed")) is not bool:raise ValueError(RESIM+" Initial execution missing")
        nonnegative_int(execution.get("body_count"),"initial body_count");nonnegative_int(execution.get("steps"),"initial steps")
        if execution!=expected:raise ValueError(RESIM+" Initial execution/spawn mismatch")

def nonnegative_int(value,label):
    if type(value) is not int or value<0:raise ValueError(RESIM+" Invalid "+label+"; expected nonnegative integer")

def settling(value):
    if not isinstance(value,str) or not value:raise ValueError(RESIM+" Invalid settling status")

def origin_metrics(record):
    nonnegative_int(record.get("steps"),"origin/source steps");settling(record.get("settling_status"))

def bundle_metrics(bundle):
    nonnegative_int(bundle.get("source_steps"),"source_steps");settling(bundle.get("settling_status"))

def execution_metrics(record,request):
    origin_metrics(record);nonnegative_int(record.get("source_steps"),"source_steps")
    execution=record.get("execution")
    if not isinstance(execution,dict) or set(execution)!={"physics_executed","body_count","steps"} or type(execution.get("physics_executed")) is not bool:raise ValueError(RESIM+" Invalid execution record")
    nonnegative_int(execution["steps"],"execution.steps");nonnegative_int(execution["body_count"],"execution.body_count")
    if record["steps"]!=record["source_steps"]:raise ValueError(RESIM+" Result steps/source_steps mismatch")
    operation=request.get("operation")
    if operation=="bake":
        if execution!={"physics_executed":False,"body_count":0,"steps":0}:raise ValueError(RESIM+" Source rebake execution")
    elif operation in ("simulate","simulate_bake"):
        executed=bool(record["poses"]) if record["physics_input_format_version"] in (2,3) else True
        if execution!={"physics_executed":executed,"body_count":len(record["poses"]),"steps":record["source_steps"]}:raise ValueError(RESIM+" Source simulation execution")
        origin=record["pose_origin"]
        if any(origin.get(key)!=record.get(key) for key in ("job_id","worker_version","physics_contract_version")):raise ValueError(RESIM+" Initial simulation origin identity mismatch")
    else:raise ValueError(RESIM+" Unknown source operation")

class Blobs:
    def __init__(self):self.data={};self.total=0;self.paths={}
    def add(self,data,expected=None):
        digest=sha(data)
        if expected is not None and digest!=expected:raise ValueError(RESIM+" Raw SHA mismatch")
        if len(data)>LIMIT:raise ValueError("Provenance file exceeds 16 MiB")
        if digest not in self.data:
            if self.total+len(data)>TOTAL:raise ValueError("Provenance exceeds 128 MiB unique budget")
            self.total+=len(data);self.data[digest]=data
        return digest
    def read(self,path,expected=None):
        path=logical_path(path);size=io_path(path).stat().st_size
        if size>LIMIT:raise ValueError("Provenance file exceeds 16 MiB")
        if expected not in self.data and str(path) not in self.paths and self.total+size>TOTAL:raise ValueError("Provenance exceeds 128 MiB unique budget before read")
        with io_path(path).open("rb") as stream:data=stream.read(LIMIT+1)
        if len(data)!=size or io_path(path).stat().st_size!=size:raise ValueError("Provenance changed during read")
        digest=self.add(data,expected);self.paths[str(path)]=digest
        return digest,json.loads(data)
    def json(self,digest):return json.loads(self.data[digest])
    def save(self,directory,already_present=()):
        out=Path(directory)/"provenance";io_path(out).mkdir()
        for digest,data in self.data.items():
            if digest in already_present:continue
            if len(data)>LIMIT:raise ValueError("Provenance file exceeds budget before copy")
            with io_path(out/(digest+".json")).open("xb") as stream:stream.write(data)

def legacy_key_material(request):
    # The original Python 0.2.0 key() used default separators and retained raw numeric types.
    assets=[{k:r[k] for k in ("asset_id","content_hash","format","weight","scale")} for r in sorted(request["assets"],key=lambda r:r["asset_id"])]
    return encoded(dict(assets=assets,simulation=request["simulation"],worker="0.2.0"))

def safe_result(root,identity):
    root=logical_path(root);path=logical_path(root/"runs"/run_id(identity)/"result.json")
    if not path.is_relative_to(root) or path.parent.name!=identity:raise ValueError(RESIM+" Owned run path escape")
    return path
def cache_path(root,content_hash):
    if not isinstance(content_hash,str) or not re.fullmatch("[0-9a-f]{64}",content_hash):raise ValueError(RESIM+" Invalid content hash")
    root=logical_path(root);path=logical_path(root/"assets"/(content_hash+".obj"))
    if not path.is_relative_to(root):raise ValueError(RESIM+" Asset cache path escape")
    return path
def previous_id(value):
    if not isinstance(value,str):raise ValueError(RESIM)
    if not Path(value).is_absolute():raise ValueError(RESIM+" Legacy poses path must be absolute")
    parts=value.replace("\\","/").split("/")
    if len(parts)<3 or parts[-1]!="result.json" or parts[-3]!="runs" or ".." in parts:raise ValueError(RESIM+" Invalid old poses_path")
    return run_id(parts[-2])
def legacy_previous(request):
    identity=previous_id(request.get("poses_path"));old=request["poses_path"].replace("\\","/")
    output=request["output_directory"].replace("\\","/")
    if "/runs/" not in output or output.rsplit("/runs/",1)[1]!=request["job_id"] or output.rsplit("/runs/",1)[0]!=old.rsplit("/runs/",1)[0]:raise ValueError(RESIM+" Legacy path root mismatch")
    return identity
def local_ref(run,relative):
    if not isinstance(relative,str) or Path(relative).is_absolute():raise ValueError(RESIM+" Absolute provenance ref")
    resolved=logical_path(run/relative)
    if not resolved.is_relative_to(logical_path(run)):raise ValueError(RESIM+" Provenance path escape")
    return resolved

def legacy_chain(root,identity,wanted,blobs):
    chain=[];seen=set();poses=None;key=None;source_steps=None;source_settling=None
    while True:
        identity=run_id(identity)
        if identity in seen or len(seen)>=64:raise ValueError(RESIM+" Cyclic/long legacy chain")
        seen.add(identity);path=safe_result(root,identity)
        result_sha,result=blobs.read(path);request_sha,request=blobs.read(path.with_name("request.json"))
        if result.get("schema_version")!=2 or result.get("worker_version")!="0.2.0" or NEW_FIELDS.intersection(result):raise ValueError(RESIM+" Not pure legacy 0.2.0")
        if request.get("schema_version")!=2 or NEW_FIELDS.intersection(request) or "worker_version" in request:raise ValueError(RESIM+" Partial legacy request")
        if request.get("job_id")!=identity or result.get("job_id")!=identity or request.get("simulation_key")!=result.get("simulation_key"):raise ValueError(RESIM+" Legacy job/key mismatch")
        if inputs(request["assets"],request["simulation"])!=wanted or asset_identity(result["assets"])!=wanted["assets"]:raise ValueError(RESIM+" Physics settings changed")
        if result.get("coordinate_system")!="RH_Z_UP" or result.get("units")!="meters":raise ValueError(RESIM+" Legacy coordinates/units")
        validate_raw_poses(result["poses"],request["assets"])
        origin_metrics(result)
        if len(result["poses"])!=wanted["simulation"]["count"]:raise ValueError(RESIM+" Pose count mismatch")
        if poses is None:poses=copy.deepcopy(result["poses"]);key=result["simulation_key"];source_steps=result["steps"];source_settling=result["settling_status"]
        if result["poses"]!=poses or result["simulation_key"]!=key:raise ValueError(RESIM+" Legacy poses/key changed")
        if result["steps"]!=source_steps or result["settling_status"]!=source_settling:raise ValueError(RESIM+" Legacy source steps/settling changed")
        material=legacy_key_material(request);material_sha=blobs.add(material)
        if material_sha!=key:raise ValueError(RESIM+" Old Python key mismatch")
        chain.append(dict(job_id=identity,request_sha256=request_sha,result_sha256=result_sha,key_material_sha256=material_sha))
        operation=request.get("operation")
        if operation in ("simulate","simulate_bake"):return chain,result
        if operation!="bake":raise ValueError(RESIM+" Legacy operation")
        identity=legacy_previous(request)

def source(root,current,wanted):
    blobs=Blobs();identity=run_id(current["job_id"]);run=safe_result(root,identity).parent
    result_sha,result=blobs.read(run/"result.json");request_sha,request=blobs.read(run/"request.json")
    if result.get("schema_version")!=2:raise ValueError(RESIM)
    if result.get("worker_version")=="0.2.0" and not NEW_FIELDS.intersection(result):
        wanted=stored_inputs(wanted,1)
        chain,first=legacy_chain(root,identity,wanted,blobs)
        origin=dict(job_id=first["job_id"],worker_version="0.2.0",physics_contract_version=1,record_sha256=chain[-1]["result_sha256"])
        bundle=dict(kind="legacy",input_format_version=1,legacy_chain=chain,origin_kind="legacy_result",origin=origin,key_scheme="legacy_0_2_0",simulation_key=first["simulation_key"],poses=copy.deepcopy(first["poses"]),source_steps=first["steps"],settling_status=first["settling_status"])
    else:
        formats(result);formats(request);semantics(result);semantics(request);semantics(result["pose_envelope"])
        wanted=stored_inputs(wanted,result["physics_input_format_version"])
        if request.get("schema_version")!=2 or result.get("status")!="completed" or any(result[k]!=request[k] for k in VERSIONS) or request.get("operation")!=result.get("operation"):raise ValueError(RESIM+" Source execution contract")
        execution_metrics(result,request)
        if request.get("job_id")!=identity or result.get("job_id")!=identity or request.get("worker_version")!=result["worker_version"]:raise ValueError(RESIM+" Source identity")
        if inputs(request["assets"],request["simulation"],request.get("scatter_mask"),request["physics_input_format_version"])!=wanted:raise ValueError(RESIM+" Physics settings changed")
        input_sha,physical=blobs.read(run/"physics_inputs.json",result["physics_input_hash"])
        if result["physics_input_format_version"]==3:
            stored_inputs(physical,3)
            expected_key=simulation_key(input_sha,3)
            for document in (request,result):
                if type(document.get("key_scheme")) is not str or document["key_scheme"]!="physics_input_v1" or type(document.get("simulation_key")) is not str or document["simulation_key"]!=expected_key:raise ValueError(RESIM+" Input3 request/result raw key mismatch")
        if physical!=wanted or request.get("physics_input_hash")!=input_sha:raise ValueError(RESIM+" Physics input identity")
        validate_raw_poses(result["poses"],request["assets"],wanted["physics_input_format_version"])
        if wanted["physics_input_format_version"]==1:
            if len(result["poses"])!=wanted["simulation"]["count"]:raise ValueError(RESIM+" Pose count mismatch")
        else:spawn_metrics(result,wanted,root)
        envelope=result["pose_envelope"]
        if envelope.get("poses")!=result["poses"] or envelope.get("pose_format_version")!=1 or envelope.get("simulation_key")!=result["simulation_key"] or envelope.get("physics_input_hash")!=input_sha or envelope.get("key_scheme")!=result["key_scheme"] or envelope.get("origin")!=result["pose_origin"]:raise ValueError(RESIM+" Envelope mismatch")
        origin=result["pose_origin"];run_id(origin["job_id"])
        origin_sha,record=blobs.read(local_ref(run,result["origin"]["record_path"]),origin["record_sha256"])
        origin_metrics(record)
        if result["origin"].get("record_sha256")!=origin_sha:raise ValueError(RESIM+" Origin reference mismatch")
        bundle=dict(kind="new",input_format_version=result["physics_input_format_version"],origin_kind=result["origin"]["kind"],origin=origin,key_scheme=result["key_scheme"],simulation_key=result["simulation_key"],poses=copy.deepcopy(result["poses"]),source_steps=result["source_steps"],settling_status=result["settling_status"],source_input_sha256=input_sha)
        if result["operation"]=="bake":
            pose_source_sha,prior_bundle=blobs.read(run/"pose_source.json",request["pose_source_hash"])
            if result["physics_input_format_version"]==3:
                if type(prior_bundle) is not dict or type(prior_bundle.get("input_format_version")) is not int or prior_bundle["input_format_version"]!=3 or type(prior_bundle.get("key_scheme")) is not str or prior_bundle["key_scheme"]!="physics_input_v1" or type(prior_bundle.get("simulation_key")) is not str or prior_bundle["simulation_key"]!=expected_key:raise ValueError(RESIM+" Consumed input3 format/scheme/raw key mismatch")
            bundle_metrics(prior_bundle)
            if prior_bundle.get("source")!=result.get("rebake_source") or prior_bundle.get("origin")!=origin or prior_bundle.get("poses")!=result["poses"] or prior_bundle.get("source_steps")!=result["source_steps"] or prior_bundle.get("settling_status")!=result["settling_status"]:raise ValueError(RESIM+" Immediate rebake source provenance mismatch")
            bundle["source_pose_source_sha256"]=pose_source_sha
        if bundle["origin_kind"]=="legacy_result":
            if bundle["key_scheme"]!="legacy_0_2_0":raise ValueError(RESIM+" Legacy key scheme mismatch")
            proof=result["legacy_proof"];bundle["legacy_chain"]=proof
            for step in proof:
                for key in ("request_sha256","result_sha256","key_material_sha256"):blobs.read(run/"provenance"/(step[key]+".json"),step[key])
            # Recheck the complete legacy proof using an isolated logical tree in memory.
            validate_legacy_proof(proof,blobs,wanted,bundle)
        else:
            if bundle["origin_kind"]!="origin_result":raise ValueError(RESIM+" Unknown origin record kind")
            formats(record,True);semantics(record)
            if record.get("job_id")!=origin["job_id"] or record.get("worker_version")!=origin["worker_version"] or record.get("physics_contract_version")!=origin["physics_contract_version"] or record.get("poses")!=bundle["poses"] or record.get("physics_input_hash")!=input_sha or record.get("simulation_key")!=bundle["simulation_key"] or record.get("key_scheme")!=bundle["key_scheme"] or record.get("steps")!=bundle["source_steps"] or record.get("settling_status")!=bundle["settling_status"]:raise ValueError(RESIM+" Origin record mismatch")
            if bundle["key_scheme"]!="physics_input_v1" or simulation_key(input_sha,origin["physics_contract_version"])!=bundle["simulation_key"]:raise ValueError(RESIM+" Origin key mismatch")
            if wanted["physics_input_format_version"] in (2,3):
                version=wanted["physics_input_format_version"]
                if record["physics_contract_version"]!=version or (version==3 and record["physics_input_format_version"]!=3):raise ValueError(RESIM+" Input2/3 origin physics/input mismatch")
                spawn_metrics(record,wanted,root,initial=True)
                if any(result.get(field)!=record[field] for field in SPAWN_FIELDS):raise ValueError(RESIM+" Result spawn metadata differs from origin")
                if result["operation"]=="bake" and prior_bundle.get("spawn")!={field:record[field] for field in SPAWN_FIELDS}:raise ValueError(RESIM+" Consumed spawn differs from origin")
                bundle["spawn"]={field:copy.deepcopy(record[field]) for field in SPAWN_FIELDS}
    bundle.update(source=dict(job_id=identity,worker_version=result["worker_version"],record_sha256=result_sha),source_request_sha256=request_sha)
    return bundle,blobs

def validate_legacy_proof(chain,blobs,wanted,bundle):
    bundle_metrics(bundle)
    if not 1<=len(chain)<=64:raise ValueError(RESIM+" Legacy chain limit")
    if bundle["origin"].get("worker_version")!="0.2.0" or type(bundle["origin"].get("physics_contract_version")) is not int or bundle["origin"]["physics_contract_version"]!=1:raise ValueError(RESIM+" Legacy origin producer mismatch")
    seen=set()
    for index,step in enumerate(chain):
        identity=run_id(step["job_id"])
        if identity in seen:raise ValueError(RESIM+" Legacy cycle")
        seen.add(identity);request=blobs.json(step["request_sha256"]);result=blobs.json(step["result_sha256"])
        origin_metrics(result)
        if result.get("worker_version")!="0.2.0" or result.get("schema_version")!=2 or NEW_FIELDS.intersection(result) or NEW_FIELDS.intersection(request) or "worker_version" in request:raise ValueError(RESIM)
        if request.get("job_id")!=identity or result.get("job_id")!=identity or inputs(request["assets"],request["simulation"])!=wanted or asset_identity(result["assets"])!=wanted["assets"]:raise ValueError(RESIM)
        if result["poses"]!=bundle["poses"] or result["simulation_key"]!=bundle["simulation_key"] or request["simulation_key"]!=bundle["simulation_key"]:raise ValueError(RESIM)
        if result["steps"]!=bundle["source_steps"] or result["settling_status"]!=bundle["settling_status"]:raise ValueError(RESIM+" Legacy source steps/settling mismatch")
        if blobs.data[step["key_material_sha256"]]!=legacy_key_material(request) or step["key_material_sha256"]!=bundle["simulation_key"]:raise ValueError(RESIM)
        if result.get("coordinate_system")!="RH_Z_UP" or result.get("units")!="meters":raise ValueError(RESIM)
        if index+1<len(chain):
            if request.get("operation")!="bake" or legacy_previous(request)!=chain[index+1]["job_id"]:raise ValueError(RESIM)
        elif request.get("operation") not in ("simulate","simulate_bake") or result["job_id"]!=bundle["origin"]["job_id"] or step["result_sha256"]!=bundle["origin"]["record_sha256"]:raise ValueError(RESIM)
