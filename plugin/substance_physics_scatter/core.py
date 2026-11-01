"""Host-independent job validation and transactional result selection."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
import shutil
from pathlib import Path
import struct
import uuid
import zlib
from . import compat
from . import maskio
from . import mask_source
from . import graph_companion
from .fileio import io_path,logical_path

VERSION = "0.3.0"
LEGACY_REBAKE = "이 결과는 이전 버전으로 생성되었습니다. Simulate + Bake를 실행하여 새 형식으로 생성하세요."
MIB = 1024 * 1024

def asset_identity(rows):
    return [{k: row[k] for k in ("asset_id", "content_hash", "format", "weight", "scale")}
            for row in sorted(rows, key=lambda row: row["asset_id"])]

def validate_weights(rows):
    maximum = max(row["weight"] for row in rows)
    if maximum <= 0:
        raise ValueError("At least one positive weight is required")
    total = correction = 0.0
    for row in sorted(rows, key=lambda row: row["asset_id"]):
        if row["weight"] == 0:
            continue
        value = row["weight"] / maximum
        if value == 0:
            raise ValueError("Positive weight underflow")
        y = value - correction
        next_total = total + y
        correction = (next_total - total) - y
        if not math.isfinite(next_total) or next_total <= total:
            raise ValueError("Weight cumulative precision loss")
        total = next_total

def validate_poses(poses, assets, *, allow_empty=False):
    if not isinstance(poses, list) or not (0 if allow_empty else 1) <= len(poses) <= 5000:
        raise ValueError("Invalid poses array")
    known = {row["asset_id"] for row in assets}
    seen = set()
    for pose in poses:
        identity = pose["id"]
        p, q, scale = pose["position"], pose["rotation"], pose["scale"]
        if type(identity) is not int or identity < 0 or identity in seen or pose["asset_id"] not in known:
            raise ValueError("Invalid/duplicate pose id or unknown asset")
        seen.add(identity)
        if not isinstance(p, list) or not isinstance(q, list) or len(p) != 3 or len(q) != 4:
            raise ValueError("Invalid pose shape")
        if not all(type(v) in (int, float) and math.isfinite(v) for v in p + q + [scale]) or not 0 < scale <= 100:
            raise ValueError("Invalid pose value/scale")
        length = sum(v * v for v in q)
        if abs(length - 1) > 1e-3:
            raise ValueError("Rotation quaternion is not normalized")
        # Preserve raw pose provenance. The worker normalizes only a deep calculation copy.

def digest(path):
    h = hashlib.sha256()
    with io_path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def key(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

def atomic_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with io_path(temp).open("w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(io_path(temp), io_path(path))

def png_header(path):
    content = io_path(path).read_bytes()
    header = content[:33]
    if len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError("Invalid PNG header")
    width, height, bits, color = struct.unpack(">IIBB", header[16:26])
    if not width or not height or width>8192 or height>8192 or header[26:29]!=b"\0\0\0":raise ValueError("Invalid PNG dimensions/method/interlace")
    position = 8
    compressed = bytearray()
    ended = False
    while position + 12 <= len(content):
        length = struct.unpack(">I", content[position:position+4])[0]
        kind = content[position+4:position+8]
        data = content[position+8:position+8+length]
        end = position + 12 + length
        if end > len(content) or zlib.crc32(kind + data) & 0xffffffff != struct.unpack(">I", content[end-4:end])[0]:
            raise ValueError("Truncated/corrupt PNG")
        if kind == b"IDAT":
            compressed.extend(data)
        if kind == b"IEND":
            ended = True
            break
        position = end
    channels = {0: 1, 2: 3, 6: 4}.get(color)
    if not ended or not channels or bits not in (8, 16):
        raise ValueError("Unsupported/incomplete PNG")
    expected=height * (1 + width * channels * bits // 8);inflater=zlib.decompressobj();decoded=inflater.decompress(compressed,expected)
    if len(decoded) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError("Invalid PNG pixel payload")
    return width, height, bits, color

def empty_map(path,channel):
    content=io_path(path).read_bytes();w,h,bits,color=png_header(path);position=8;parts=[]
    while position+12<=len(content):
        size=struct.unpack(">I",content[position:position+4])[0]
        if content[position+4:position+8]==b"IDAT":parts.append(content[position+8:position+8+size])
        position+=size+12
    bpp=(3 if color==2 else 1)*bits//8;stride=w*bpp;limit=h*(stride+1);inflater=zlib.decompressobj();raw=inflater.decompress(b"".join(parts),limit)
    if len(raw)!=limit or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:raise ValueError("Invalid empty PNG")
    previous=bytearray(stride);expected=(b"\x80\x80\xff"*w) if channel=="normal" else bytes(stride)
    for row in range(h):
        offset=row*(stride+1);mode=raw[offset];line=bytearray(raw[offset+1:offset+1+stride])
        if mode>4:raise ValueError("Invalid empty PNG filter")
        if mode:
            for x in range(stride):
                a=line[x-bpp] if x>=bpp else 0;b=previous[x];c=previous[x-bpp] if x>=bpp else 0
                if mode==1:prediction=a
                elif mode==2:prediction=b
                elif mode==3:prediction=(a+b)//2
                else:
                    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);prediction=a if pa<=pb and pa<=pc else b if pb<=pc else c
                line[x]=(line[x]+prediction)&255
        if line!=expected:raise ValueError("Empty map has nonempty pixel values: "+channel)
        previous=line

def _capture_plain(value,depth=0,budget=None):
    if budget is None:budget=[0]
    budget[0]+=1
    if depth>64 or budget[0]>32768:raise ValueError("Captured mask plain data budget exceeded")
    if value is None or type(value) in (bool,int):return
    if type(value) is float:
        if not math.isfinite(value):raise ValueError("Captured mask has nonfinite data")
        return
    if type(value) is str:
        if len(value)>16384 or "\0" in value:raise ValueError("Captured mask string budget exceeded")
        return
    if type(value) is dict:
        for key,item in value.items():
            if type(key) is not str:raise ValueError("Captured mask keys must be strings")
            _capture_plain(key,depth+1,budget);_capture_plain(item,depth+1,budget)
    elif type(value) is list:
        for item in value:_capture_plain(item,depth+1,budget)
    else:raise ValueError("Captured mask must contain plain JSON values")

def _validated_capture(value):
    """Validate the host's plain capture handoff; SDK freshness remains the caller's boundary."""
    try:
        _capture_plain(value)
        raw=mask_source.encoded(value)
        if len(raw)>graph_companion.MAX_FILE:raise ValueError("Captured mask handoff exceeds 1 MiB")
        value=graph_companion.decode(raw)
    except (TypeError,RecursionError) as error:raise ValueError("Captured mask must be bounded plain JSON") from error
    mask_source.fields(value,{"png","capture","operation_authored_payload"},"captured mask")
    png=value["png"];mask_source.fields(png,{"path","sha256","decoded_u16be_sha256","width","height","bit_depth","format","bytes"},"captured PNG")
    for name,expected in (("width",512),("height",512),("bit_depth",16)):
        if type(png[name]) is not int or png[name]!=expected:raise ValueError("Captured PNG dimensions/precision differ")
    if png["format"]!="LUM16" or type(png["bytes"]) is not int or not 0<png["bytes"]<=maskio.MAX_FILE:raise ValueError("Captured PNG format/size differs")
    png["path"]=mask_source.path(png["path"]);mask_source.sha(png["sha256"]);mask_source.sha(png["decoded_u16be_sha256"])
    capture=mask_source.capture(value["capture"],historical=True)
    if "evaluator" in capture and capture["evaluator"]["output_png_sha256"]!=png["sha256"]:raise ValueError("Captured evaluator/PNG SHA differs")
    payload=value["operation_authored_payload"]
    mask_source.fields(payload,{"schema_version","registry_authored_manifest","registry_authored_sha256","producer_evidence_sha256"},"authored payload")
    if type(payload["schema_version"]) is not int or payload["schema_version"]!=1 or not isinstance(payload["registry_authored_manifest"],dict):raise ValueError("Invalid authored payload schema")
    mask_source.sha(payload["producer_evidence_sha256"])
    if mask_source.signature(payload["registry_authored_manifest"])!=mask_source.sha(payload["registry_authored_sha256"]) or mask_source.signature(payload)!=capture["context"]["authored_sha256"]:raise ValueError("Captured authored payload signature differs")
    data,_=maskio.read(png["path"],png["sha256"])
    if len(data)!=png["bytes"] or len(data)<33 or struct.unpack(">IIBBBBB",data[16:29])!=(512,512,16,0,0,0,0):raise ValueError("Captured PNG bytes/header differ")
    maskio.decode_black(data)
    return png,capture

class Jobs:
    def __init__(self, directory):
        self.directory = logical_path(directory)
        io_path(self.directory).mkdir(parents=True, exist_ok=True)
        self.active = None
        self.cancelled = set()
        self._host_pending = {}

    @property
    def current(self):
        path = self.directory / "current.json"
        if not io_path(path).exists():
            return None
        current = json.loads(io_path(path).read_text(encoding="utf-8"))
        # Resolve owned paths from identity, even if the old location still exists after a copy.
        run = compat.safe_result(self.directory,current["job_id"]).parent
        current["result_path"] = str(run / "result.json")
        current["files"] = {channel: str(run / (channel + ".png")) for channel in ("height", "normal", "coverage")}
        current["request"]["output_directory"] = str(run)
        request = current["request"]
        if request.get("schema_version", 1) == 1:
            cached = compat.cache_path(self.directory,request["input_hash"])
            if io_path(cached).exists():
                request["asset_path"] = str(cached)
        else:
            for row in request["assets"]:
                row["path"] = str(compat.cache_path(self.directory,row["content_hash"]))
            if "result" in current:
                current["result"]["assets"] = request["assets"]
            if "physics_input_hash" in request:
                request["physics_inputs_path"]=str(run/"physics_inputs.json")
                if request.get("operation")=="bake":request["pose_source_path"]=str(run/"pose_source.json")
            if request.get("scatter_mask") is not None:request["scatter_mask"]["path"]=str(maskio.cache_path(self.directory,request["scatter_mask"]["content_hash"]))
        graph_companion.read(self.directory,current)
        return current

    def prepare(self, mesh, simulation, bake, *, rebake=False,scatter_mask=None,host_mode="current_file",captured_mask=None):
        if host_mode not in ("current_file","current_graph_terminal","saved_input"):raise ValueError("Invalid host input mode")
        if host_mode=="current_file" and captured_mask is not None:raise ValueError("File input cannot contain graph capture")
        if host_mode=="current_graph_terminal" and (captured_mask is None or scatter_mask is not None):raise ValueError("Graph input needs only a fresh captured mask")
        if host_mode=="saved_input" and (rebake is not True or captured_mask is not None or scatter_mask is not None):raise ValueError("Saved input needs rebake without external inputs")
        previous = self.current
        prior=graph_companion.read(self.directory,previous) if previous is not None else None
        mask_source.input_policy(prior["record"] if prior else None,rebake=rebake,mode=host_mode)
        png=capture=None
        if host_mode=="current_graph_terminal":
            png,capture=_validated_capture(captured_mask);scatter_mask=png["path"]
        elif host_mode=="saved_input":
            if previous is None:raise ValueError("Saved input requires a previous result")
            identity=maskio.identity(previous["request"].get("scatter_mask"))
            if identity is not None:
                cached=maskio.cache_path(self.directory,identity["content_hash"])
                data,_=maskio.read(cached,identity["content_hash"]);maskio.decode_black(data)
                scatter_mask=dict(identity,path=str(cached))
        if rebake and previous and previous["request"].get("schema_version", 1) == 1:
            raise ValueError(LEGACY_REBAKE)
        simulation = dict(simulation)
        if isinstance(mesh, (str, Path)):
            # Stable compatibility identity is independent of content and scale.
            rows = [{"asset_id": "00000000000000000000000000000001", "path": str(mesh),
                     "format": "obj", "weight": 1.0, "scale": simulation.pop("scale", .3)}]
        else:
            rows = [dict(row) for row in mesh]
            if "scale" in simulation:
                raise ValueError("Global scale is not supported in schema v2")
        input_version=3 if simulation.get("edges")=="periodic" else 2
        simulation=compat.simulation(simulation,version=input_version)
        if not 1 <= len(rows) <= 1024:
            raise ValueError("assets needs 1..1024 entries")
        seen, total = set(), 0
        for row in rows:
            identity = row.get("asset_id", "")
            if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity) or identity in seen:
                raise ValueError("Invalid or duplicate asset_id")
            seen.add(identity)
            if row.get("format", "obj") != "obj":
                raise ValueError("Only OBJ is supported")
            row["format"] = "obj"
            for field, low, high in (("weight", 0, float("inf")), ("scale", 0, 100)):
                value = row.get(field, 1)
                if type(value) not in (int, float) or not math.isfinite(value) or value < low or value > high or (field == "scale" and value == 0):
                    raise ValueError("Invalid asset " + field)
                row[field] = float(value)
                if field=="weight" and value==0:row[field]=0.
            source = logical_path(row["path"])
            row.setdefault("source_name", source.name)
            if not io_path(source).is_file() and row.get("content_hash"):
                source = compat.cache_path(self.directory,row["content_hash"])
            size = io_path(source).stat().st_size
            total += size
            if size > 256 * MIB or total > 512 * MIB:
                raise ValueError("OBJ input exceeds per-file/aggregate byte budget")
            row["path"] = str(source)
            row["_source_size"] = size
        validate_weights(rows)
        assets = self.directory / "assets"
        io_path(assets).mkdir(exist_ok=True)
        for row in rows:
            source = Path(row["path"])
            if io_path(source).stat().st_size != row.pop("_source_size"):
                raise ValueError("Input size changed before cache copy")
            asset_hash = digest(source)
            cached = compat.cache_path(self.directory,asset_hash)
            if not io_path(cached).exists():
                temporary = assets / (uuid.uuid4().hex + ".tmp")
                try:
                    shutil.copyfile(io_path(source), io_path(temporary))
                    if digest(temporary) != asset_hash:
                        raise ValueError("Input changed during cache copy")
                    os.replace(io_path(temporary), io_path(cached))
                finally:
                    io_path(temporary).unlink(missing_ok=True)
            if digest(cached) != asset_hash:
                raise ValueError("Cached mesh content changed")
            row["content_hash"], row["path"] = asset_hash, str(cached)
        rows.sort(key=lambda row: row["asset_id"])
        mask=maskio.snapshot(self.directory,scatter_mask)
        if png is not None:
            if mask is None or mask["content_hash"]!=png["sha256"]:raise ValueError("Capture/cache SHA mismatch")
            maskio.read(maskio.cache_path(self.directory,mask["content_hash"]),png["sha256"])
        physical=compat.inputs(rows,simulation,mask,version=input_version);physical_bytes=compat.encoded(physical);physical_hash=compat.sha(physical_bytes)
        bundle=blobs=None
        sim_key=compat.simulation_key(physical_hash,3 if input_version==3 else 2)
        scheme="physics_input_v1"
        if rebake:
            if not previous:raise ValueError("Simulation settings changed. Run Simulate first.")
            try:bundle,blobs=compat.source(self.directory,previous,physical)
            except (OSError,KeyError,TypeError) as error:raise ValueError(compat.RESIM+" "+str(error)) from error
            sim_key=bundle["simulation_key"];scheme=bundle["key_scheme"]
            physical=compat.stored_inputs(physical,bundle["input_format_version"])
            physical_bytes=compat.encoded(physical);physical_hash=compat.sha(physical_bytes)
            if bundle.get("source_input_sha256"):
                physical_hash=bundle["source_input_sha256"];physical_bytes=blobs.data[physical_hash]
        job_id = uuid.uuid4().hex
        directory = compat.safe_result(self.directory,job_id).parent
        io_path(directory).mkdir(parents=True)
        request = {
            "schema_version": 2, "job_id": job_id,
            "operation": "bake" if rebake else "simulate_bake",
            "assets": rows,
            "simulation": simulation, "bake": bake,
            "output_directory": str(directory), "simulation_key": sim_key,
            "worker_version":VERSION,**compat.versions_for_input(physical["physics_input_format_version"]),**compat.SEMANTICS,
            "physics_input_hash":physical_hash,"physics_inputs_path":str(directory/"physics_inputs.json"),"key_scheme":scheme,
            "scatter_mask":mask,
        }
        request["physics_input_format_version"]=physical["physics_input_format_version"]
        if physical["physics_input_format_version"]==3:request["periodic"]=dict(compat.PERIODIC)
        with io_path(directory/"physics_inputs.json").open("xb") as stream:stream.write(physical_bytes)
        if rebake:
            blobs.save(directory,already_present=(physical_hash,))
            atomic_json(directory/"pose_source.json",bundle)
            request["pose_source_path"]=str(directory/"pose_source.json")
            request["pose_source_hash"]=digest(directory/"pose_source.json")
        atomic_json(directory / "request.json", request)
        pointer=graph_companion.write(self.directory,request,mode=host_mode,capture=capture,previous=previous) if host_mode!="current_file" else None
        sealed=copy.deepcopy(pointer)
        pending=dict(self._host_pending)
        if self.active is not None:pending.pop(self.active["job_id"],None)
        pending[job_id]=sealed
        self._host_pending=pending
        self.active = request
        return directory / "request.json"

    def cancel(self):
        if self.active:
            self.cancelled.add(self.active["job_id"])
            self._host_pending.pop(self.active["job_id"],None)
            self.active = None

    def validate(self, path, job_id):
        request = self.active
        if not request or request["job_id"] != job_id or job_id in self.cancelled:
            raise ValueError("Stale or cancelled job")
        expected = logical_path(request["output_directory"])
        path = logical_path(path)
        if path != expected / "result.json":
            raise ValueError("Result path outside current job")
        result = json.loads(io_path(path).read_text(encoding="utf-8"))
        if result.get("job_id") != job_id or result.get("schema_version") != 2 or result.get("status") != "completed":
            raise ValueError("Invalid result identity/status")
        if result.get("worker_version") != VERSION or asset_identity(result.get("assets", [])) != asset_identity(request["assets"]):
            raise ValueError("Result input/version mismatch")
        if result.get("simulation_key") != request["simulation_key"] or any(digest(row["path"]) != row["content_hash"] for row in request["assets"]):
            raise ValueError("Consumed input changed")
        validate_poses(result.get("poses"), request["assets"],allow_empty=request["physics_input_format_version"] in (2,3))
        if request["physics_input_format_version"]==1 and len(result["poses"])!=request["simulation"]["count"]:raise ValueError("Result pose count mismatch")
        compat.formats(result);compat.semantics(result)
        if any(result.get(k)!=request[k] for k in compat.VERSIONS) or result.get("physics_input_hash")!=request["physics_input_hash"] or result.get("key_scheme")!=request["key_scheme"] or result.get("operation")!=request["operation"]:
            raise ValueError("Execution contract mismatch")
        envelope=result["pose_envelope"];compat.semantics(envelope)
        if envelope.get("pose_format_version")!=1 or envelope.get("poses")!=result["poses"] or envelope.get("origin")!=result["pose_origin"] or envelope.get("physics_input_hash")!=request["physics_input_hash"] or envelope.get("simulation_key")!=request["simulation_key"] or envelope.get("key_scheme")!=request["key_scheme"]:raise ValueError("Pose envelope mismatch")
        operation=request["operation"]
        execution=result["execution"]
        if operation=="bake" and execution!={"physics_executed":False,"body_count":0,"steps":0}:raise ValueError("Rebake executed physics")
        origin=result["origin"]
        if origin["record_sha256"]!=result["pose_origin"]["record_sha256"]:raise ValueError("Origin raw SHA mismatch")
        try:compat.source(self.directory,{"job_id":job_id},compat.inputs(request["assets"],request["simulation"],request.get("scatter_mask"),request["physics_input_format_version"]))
        except (OSError,KeyError,TypeError) as error:raise ValueError("Invalid immutable result provenance: "+str(error)) from error
        maps = result["maps"]
        res = request["bake"]["resolution"]
        files = {}
        for channel, bits, color in (("height", 16, 0), ("normal", 8, 2), ("coverage", 8, 0)):
            image = logical_path(expected / maps[channel])
            if image.parent != expected or png_header(image) != (res, res, bits, color):
                raise ValueError("Invalid map path/format: " + channel)
            files[channel] = str(image)
            if not result["poses"]:empty_map(image,channel)
        if not result["poses"]:
            low=request["bake"].get("height_min",0);high=request["bake"].get("height_max",2)
            if not low<high or maps.get("height_min")!=low or maps.get("height_max")!=high or maps.get("clipped_samples")!=0:raise ValueError("Empty map metadata invalid")
        candidate={"job_id": job_id, "result_path": str(path), "simulation_key": request["simulation_key"],
                "files": files, "hashes": {k: digest(v) for k, v in files.items()},
                "request": request, "result": result}
        if job_id not in self._host_pending:raise ValueError("Host preparation state missing")
        pointer=self._host_pending[job_id]
        if pointer is not None:candidate[graph_companion.KEY]=copy.deepcopy(pointer)
        self._verify_host(candidate)
        return candidate

    def _verify_host(self,candidate):
        job=candidate["job_id"]
        if job not in self._host_pending:raise ValueError("Host preparation state missing")
        pointer=self._host_pending[job]
        if pointer is None:
            if graph_companion.KEY in candidate:raise ValueError("Unclaimed host companion reference")
        elif graph_companion.KEY not in candidate or graph_companion.reference(candidate[graph_companion.KEY])!=pointer:raise ValueError("Sealed host companion reference differs")
        graph_companion.read(self.directory,candidate)

    def promote(self, candidate):
        if not self.active or candidate["job_id"] != self.active["job_id"]:
            raise ValueError("Candidate no longer active")
        self._verify_host(candidate)
        atomic_json(self.directory / "current.json", candidate)
        self._host_pending.pop(candidate["job_id"],None)
        self.active = None
