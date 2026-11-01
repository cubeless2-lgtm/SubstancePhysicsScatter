"""Bounded immutable host-only terminal provenance. Native identities are untouched."""
from __future__ import annotations
import copy,hashlib,json,os,uuid
from . import compat,maskio,mask_source as values
from .fileio import io_path,logical_path

KEY="graph_mask_source"
NAME="graph_mask_source.json"
MAX_FILE=1024*1024
MAX_TOTAL=3*MAX_FILE
MISSING=object()
METADATA_NOT_CHECKED=object()
COMMON={"schema_version","job_id","operation","mode","snapshot_sha256","capture_available","pile_origin_available","pile_origin","previous_source"}

def owned_run(root,job_id):return compat.safe_result(root,values.run_id(job_id)).parent
def owned(run,path):
    run=logical_path(run);path=logical_path(path)
    if not path.is_relative_to(run) or path==run:raise ValueError("Host companion path escapes run")
    return path
def reference(value):
    values.fields(value,{"path","sha256","schema_version"},"host companion reference")
    if value["path"]!=NAME or type(value["schema_version"]) is not int or value["schema_version"] not in (1,2):raise ValueError("Unsupported companion reference")
    values.sha(value["sha256"])
    return copy.deepcopy(value)
def pairs(items):
    result={}
    for k,v in items:
        if k in result:raise ValueError("Duplicate companion JSON field")
        result[k]=v
    return result
def decode(raw):
    if not isinstance(raw,bytes) or len(raw)>MAX_FILE:raise ValueError("Companion exceeds 1 MiB")
    return json.loads(raw,object_pairs_hook=pairs)

def legacy_capture(value):
    keys={"pre_signature_sha256","post_signature_sha256","designer_version","package_path","package_uid","graph_url","instance_path","source_node_id","output_id","captured_at"}
    values.fields(value,keys,"schema1 capture")
    if values.sha(value["pre_signature_sha256"])!=values.sha(value["post_signature_sha256"]):raise ValueError("Legacy capture authored signature differs")
    values.path(value["package_path"],resolve=False);values.package_uid(value["package_uid"]);values.timestamp(value["captured_at"])
    for k in ("designer_version","graph_url","source_node_id","output_id"):values.text(value[k],k)
    if not isinstance(value["instance_path"],list) or len(value["instance_path"])>256:raise ValueError("Invalid instance path")
    for p in value["instance_path"]:values.text(p,"instance path part",512)

def document(value):
    if not isinstance(value,dict) or type(value.get("schema_version")) is not int or value["schema_version"] not in (1,2):raise ValueError("Unknown host companion schema")
    version=value["schema_version"];current="current_graph_terminal" if version==2 else "current_graph";mode=value.get("mode")
    extra={"capture","source_kind"} if mode==current and version==2 else {"capture"} if mode==current else set()
    values.fields(value,COMMON|extra,"companion")
    values.run_id(value["job_id"])
    if value["operation"] not in ("simulate","simulate_bake","bake") or mode not in (current,"saved_input"):raise ValueError("Invalid companion operation/mode")
    if type(value["capture_available"]) is not bool or type(value["pile_origin_available"]) is not bool:raise ValueError("Availability must be bool")
    if value["snapshot_sha256"] is not None:values.sha(value["snapshot_sha256"])
    if mode==current:
        if value["capture_available"] is not True or value["snapshot_sha256"] is None:raise ValueError("Current graph requires capture and snapshot")
        if version==2:
            if value["source_kind"]!="graph_terminal":raise ValueError("Invalid terminal source kind")
            if values.capture(value["capture"],historical=True)!=value["capture"]:raise ValueError("Capture is not normalized")
            if "evaluator" in value["capture"] and value["capture"]["evaluator"]["output_png_sha256"]!=value["snapshot_sha256"]:raise ValueError("Evaluator/mask snapshot SHA differs")
        else:legacy_capture(value["capture"])
    elif value["capture_available"] is not False or value["operation"]!="bake":raise ValueError("Saved input requires rebake without capture")
    origin=value["pile_origin"];previous=value["previous_source"]
    if value["pile_origin_available"]:
        if not isinstance(origin,dict) or origin.get("kind") not in ("self","blob"):raise ValueError("Invalid pile origin")
        values.fields(origin,{"kind","job_id"}|({"sha256"} if origin["kind"]=="blob" else set()),"pile origin")
        values.run_id(origin["job_id"])
        if origin["kind"]=="blob":
            values.sha(origin["sha256"])
            if origin["job_id"]==value["job_id"] or value["operation"]!="bake":raise ValueError("Cyclic/incorrect origin blob")
        elif origin["job_id"]!=value["job_id"] or value["operation"]=="bake" or not value["capture_available"]:raise ValueError("Invalid self origin")
    elif origin is not None:raise ValueError("Unavailable origin must be null")
    if value["operation"]=="bake":
        values.fields(previous,{"job_id","companion_available","sha256"},"previous source")
        values.run_id(previous["job_id"])
        if previous["job_id"]==value["job_id"] or type(previous["companion_available"]) is not bool:raise ValueError("Cyclic previous source")
        if previous["companion_available"]:values.sha(previous["sha256"])
        elif previous["sha256"] is not None:raise ValueError("Unavailable previous SHA must be null")
    elif previous is not None or not value["pile_origin_available"] or origin["kind"]!="self":raise ValueError("New graph simulation must have self origin only")
    return value

class Bundle:
    def __init__(self):self.raw={};self.total=0
    def read(self,path,expected=None):
        size=io_path(path).stat().st_size
        if size>MAX_FILE or self.total+size>MAX_TOTAL:raise ValueError("Host companion byte budget exceeded before read")
        with io_path(path).open("rb") as stream:raw=stream.read(MAX_FILE+1)
        if len(raw)!=size or io_path(path).stat().st_size!=size:raise ValueError("Host companion changed during read")
        digest=hashlib.sha256(raw).hexdigest()
        if expected is not None and digest!=expected:raise ValueError("Host companion raw SHA mismatch")
        if digest not in self.raw:self.total+=len(raw);self.raw[digest]=raw
        elif self.raw[digest]!=raw:raise ValueError("Host blob content identity conflict")
        return raw,digest

def snapshot_hash(request):
    identity=maskio.identity(request.get("scatter_mask"))
    return None if identity is None else identity["content_hash"]

def known_links(current,digest,records,refs):
    """Check only already-read flat documents, never follow historical files."""
    known={current["job_id"]:(digest,current)}
    for role,identity,sha in refs:
        if identity in known and known[identity][0]!=sha:raise ValueError("Conflicting raw SHA for an already-read job")
        known[identity]=(sha,records[role])
    edges={job:set() for job in known}
    for job,(_,item) in known.items():
        summaries=[];origin=item["pile_origin"];previous=item["previous_source"]
        if origin is not None and origin["kind"]=="blob":summaries.append((origin["job_id"],True,origin["sha256"]))
        if previous is not None:summaries.append((previous["job_id"],previous["companion_available"],previous["sha256"]))
        for target,available,sha in summaries:
            if target not in known:continue
            if not available or sha!=known[target][0]:raise ValueError("Already-read job contradicts historical companion summary")
            edges[job].add(target)
    active=set();done=set()
    def visit(job):
        if job in active:raise ValueError("Direct cycle among already-read host documents")
        if job in done:return
        active.add(job)
        for target in edges[job]:visit(target)
        active.remove(job);done.add(job)
    for job in edges:visit(job)

def read(root,current,*,metadata_ref=METADATA_NOT_CHECKED):
    job=values.run_id(current["job_id"]);run=owned_run(root,job);path=owned(run,run/NAME);pointer=current.get(KEY,MISSING)
    if metadata_ref is not METADATA_NOT_CHECKED:
        if metadata_ref is MISSING:
            if pointer is not MISSING:raise ValueError("Designer companion pointer removed")
        else:
            reference(metadata_ref)
            if pointer is MISSING or reference(pointer)!=metadata_ref:raise ValueError("Current and Designer companion references differ")
    if pointer is MISSING:
        if io_path(path).exists() or (io_path(run/"host_provenance").exists() and any(io_path(run/"host_provenance").iterdir())):raise ValueError("Unclaimed host companion exists")
        return None
    pointer=reference(pointer);bundle=Bundle();raw,digest=bundle.read(path,pointer["sha256"]);doc=document(decode(raw))
    request=current["request"]
    if doc["job_id"]!=job or doc["schema_version"]!=pointer["schema_version"] or doc["operation"]!=request["operation"] or doc["snapshot_sha256"]!=snapshot_hash(request):raise ValueError("Host companion request/snapshot identity differs")
    if request.get("job_id")!=job:raise ValueError("Current request job differs")
    if doc["snapshot_sha256"] is not None:maskio.read(maskio.cache_path(root,doc["snapshot_sha256"]),doc["snapshot_sha256"])
    refs=[];origin=doc["pile_origin"];previous=doc["previous_source"]
    if origin is not None and origin["kind"]=="blob":refs.append(("origin",origin["job_id"],origin["sha256"]))
    if previous is not None and previous["companion_available"]:refs.append(("previous",previous["job_id"],previous["sha256"]))
    expected={s for _,_,s in refs};directory=owned(run,run/"host_provenance")
    present={p.name for p in io_path(directory).iterdir()} if io_path(directory).exists() else set()
    if len(expected)>2 or present!={s+".json" for s in expected}:raise ValueError("Host provenance blobs missing/extra")
    blobs={};records={}
    for role,identity,sha in refs:
        if sha==digest:raise ValueError("Self-referential companion SHA")
        blob_path=owned(run,directory/(values.sha(sha)+".json"))
        if sha not in blobs:blobs[sha],_=bundle.read(blob_path,sha)
        item=document(decode(blobs[sha]));records[role]=item
        if item["job_id"]!=identity:raise ValueError("Host blob role/job identity differs")
        if role=="origin" and (item["operation"] not in ("simulate","simulate_bake") or item["pile_origin"]!={"kind":"self","job_id":identity}):raise ValueError("Origin blob is not first graph simulation")
    if "previous" in records:
        p=records["previous"]
        if p["pile_origin_available"]!=doc["pile_origin_available"]:raise ValueError("Previous/origin availability differs")
        if p["pile_origin_available"]:
            prior=p["pile_origin"];expected_origin=(prior["job_id"],previous["sha256"] if prior["kind"]=="self" else prior["sha256"])
            if origin is None or (origin["job_id"],origin.get("sha256"))!=expected_origin:raise ValueError("Previous first-origin summary differs")
    known_links(doc,digest,records,refs)
    if "result" in current:
        result=current["result"]
        if result["job_id"]!=job:raise ValueError("Result/current job differs")
        if origin is not None and result["pose_origin"]["job_id"]!=origin["job_id"]:raise ValueError("Native and host first origin differ")
        if previous is not None and result["rebake_source"]["job_id"]!=previous["job_id"]:raise ValueError("Native and host previous source differ")
    return dict(record=doc,raw=raw,sha256=digest,blobs=blobs,reference=pointer)

def _atomic(path,raw):
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with io_path(temporary).open("xb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if io_path(path).exists():raise FileExistsError("Immutable companion already exists")
        os.replace(io_path(temporary),io_path(path))
    finally:io_path(temporary).unlink(missing_ok=True)

def write(root,request,*,mode,capture=None,previous=None,writer=_atomic):
    job=values.run_id(request["job_id"]);run=owned_run(root,job)
    if not io_path(run).is_dir() or logical_path(request["output_directory"])!=run:raise ValueError("Host companion requires prepared owned run")
    path=owned(run,run/NAME);directory=owned(run,run/"host_provenance")
    if io_path(path).exists() or io_path(directory).exists():raise FileExistsError("Do not overwrite host provenance")
    rebake=request["operation"]=="bake"
    prior=read(root,previous) if previous is not None and rebake else None
    if rebake and previous is None:raise ValueError("Rebake needs previous native source")
    if mode=="saved_input" and rebake and not values.graph_family(prior["record"] if prior else None):
        if capture is not None:raise ValueError("Saved input must not invent capture")
        # A plain File Mask rebake does not acquire graph-family provenance.
        snapshot_hash(request)
        return None
    doc=dict(schema_version=2,job_id=job,operation=request["operation"],mode=mode,snapshot_sha256=snapshot_hash(request),capture_available=mode=="current_graph_terminal",pile_origin_available=False,pile_origin=None,previous_source=None)
    blobs={}
    if mode=="current_graph_terminal":doc.update(source_kind="graph_terminal",capture=values.capture(capture))
    elif capture is not None:raise ValueError("Saved input must not invent capture")
    if not rebake:doc.update(pile_origin_available=True,pile_origin=dict(kind="self",job_id=job))
    else:
        doc["previous_source"]=dict(job_id=previous["job_id"],companion_available=prior is not None,sha256=prior["sha256"] if prior else None)
        if prior:
            blobs[prior["sha256"]]=prior["raw"]
            if prior["record"]["pile_origin_available"]:
                origin=prior["record"]["pile_origin"];identity=origin["job_id"];digest=prior["sha256"] if origin["kind"]=="self" else origin["sha256"]
                blobs[digest]=prior["raw"] if origin["kind"]=="self" else prior["blobs"][digest]
                doc.update(pile_origin_available=True,pile_origin=dict(kind="blob",job_id=identity,sha256=digest))
    document(doc);raw=values.encoded(doc)
    if any(len(b)>MAX_FILE for b in [raw,*blobs.values()]) or len(blobs)>2 or sum(len(b) for b in {hashlib.sha256(raw).hexdigest():raw,**blobs}.values())>MAX_TOTAL:raise ValueError("Host companion write budget exceeded")
    created=[];made_directory=False
    def put(target,data):
        try:writer(target,data)
        except Exception:
            # A hook may fail after publishing. Claim only the expected bytes.
            if io_path(target).is_file() and io_path(target).read_bytes()==data:created.append(target)
            raise
        created.append(target)
    try:
        if blobs:io_path(directory).mkdir();made_directory=True
        for digest,data in blobs.items():
            target=owned(run,directory/(digest+".json"));put(target,data)
        put(path,raw)
        pointer=dict(path=NAME,sha256=hashlib.sha256(raw).hexdigest(),schema_version=2)
        read(root,dict(job_id=job,request=request,**{KEY:pointer}))
        return pointer
    except Exception as original:
        try:
            for target in reversed(created):io_path(target).unlink(missing_ok=True)
            if made_directory:io_path(directory).rmdir()
        except Exception as recovery:raise RuntimeError(f"Companion failed: {original!r}; cleanup also failed: {recovery!r}") from original
        raise
