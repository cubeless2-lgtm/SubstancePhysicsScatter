"""Inactive explicit SDK adapter. No SDK import/call or registration on import.

Selection inspection and capture are separate operations. All returned values
are JSON data; native wrappers are confined to SDK helper calls. Native copy
serialization compatibility and actual ABI/pixel delivery remain acceptance gates.
"""
from __future__ import annotations
import copy,datetime,hashlib,json,math,os,struct,uuid,zlib
from pathlib import Path
from . import graph_registry,mask_source,maskio
from .fileio import io_path,logical_path

_SESSION_TOKEN=uuid.uuid4().hex  # Host module generation marker, not SDK generation/security.
_MAX_FILE=2*1024*1024;_MAX_READ=12*1024*1024;_JSON_FILE=1024*1024;_JSON_TOTAL=8*1024*1024;_FAILURE_RESERVE=4096
_COMMON=("$outputsize","$format","$randomseed")
_STOCK_DEFINITIONS={"sbs::compositing::"+n for n in ("fxmaps","input_color","input_grayscale","levels","output")}|{"sbs::function::"+n for n in ("add","const_float1","const_float4","cos","get_bool","get_float1","ifelse","mul","rand","sin","vector2")}|{"sbs::fxmap::paramset"}

class CaptureError(ValueError):
    def __init__(self,record):self.record=copy.deepcopy(record);super().__init__(record.get("error","Terminal inspection/capture failed"))

def _equal(a,b,label):
    if mask_source.encoded(a)!=mask_source.encoded(b):raise ValueError(label)

def _plain(value,depth=0):
    if depth>64:raise ValueError("Evidence JSON depth exceeded")
    if type(value) in (bool,int,type(None)):return
    if type(value) is float:
        if not math.isfinite(value):raise ValueError("Non-finite evidence")
        return
    if type(value) is str:
        if len(value.encode("utf-8"))>16384:raise ValueError("Evidence string exceeds16KiB")
        return
    if type(value) is list:
        for item in value:_plain(item,depth+1)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for k,item in value.items():_plain(k,depth+1);_plain(item,depth+1)
        return
    raise ValueError("Opaque/SDK/tuple in evidence")

def _json(value):
    _plain(value);raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode("utf-8")
    if len(raw)>_JSON_FILE:raise ValueError("Evidence JSON exceeds1MiB")
    return raw

class _Owned:
    def __init__(self,directory,operation_id):
        self.root=logical_path(directory);self.work=logical_path(self.root/mask_source.run_id(operation_id))
        if not self.work.is_relative_to(self.root) or self.work==self.root or not io_path(self.root).is_dir():raise ValueError("Capture requires an existing owned root")
        io_path(self.work).mkdir(exist_ok=False);self.json_bytes=0;self.read_bytes=0;self.refs=[]
    def path(self,name):
        if Path(name).name!=name or name in (".",".."):raise ValueError("Invalid owned artifact name")
        p=logical_path(self.work/name)
        if p.parent!=self.work:raise ValueError("Artifact escapes operation")
        return p
    def read(self,path):
        size=io_path(path).stat().st_size
        if not 0<size<=_MAX_FILE or self.read_bytes+size>_MAX_READ:raise ValueError("SBS readback budget exceeded")
        with io_path(path).open("rb") as stream:raw=stream.read(_MAX_FILE+1)
        if len(raw)!=size or io_path(path).stat().st_size!=size:raise ValueError("SBS changed during read")
        self.read_bytes+=size;return raw
    def evidence(self,name,value):
        raw=_json(value)
        if self.json_bytes+len(raw)>_JSON_TOTAL-_FAILURE_RESERVE:raise ValueError("Evidence total exceeds reserved8MiB budget")
        p=self.path(name+".json")
        with io_path(p).open("xb") as stream:stream.write(raw)
        with io_path(p).open("rb") as stream:check=stream.read(_JSON_FILE+1)
        if check!=raw or json.loads(check)!=json.loads(raw):raise ValueError("Evidence readback differs")
        self.json_bytes+=len(raw);ref=dict(name=p.name,path=str(p),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw));self.refs.append(ref);return ref
    def failure(self,stage,operation_id,error):
        # Constant-key bounded ASCII envelope; no arbitrary path/metadata payload.
        value=dict(status="failed",stage=str(stage)[:32],operation_id=operation_id,error_class=type(error).__name__[:64],error=str(error)[:512])
        raw=json.dumps(value,ensure_ascii=True,separators=(",",":")).encode("ascii")
        if len(raw)>_FAILURE_RESERVE:raw=json.dumps(dict(status="failed",stage=str(stage)[:32],operation_id=operation_id,error_class=type(error).__name__[:64]),ensure_ascii=True).encode("ascii")
        p=self.path("failure.json")
        with io_path(p).open("xb") as stream:stream.write(raw)
        self.json_bytes+=len(raw);return dict(path=str(p),sha256=hashlib.sha256(raw).hexdigest())

def _default_value(property_id):
    if property_id=="$outputsize":kind,typ,ident,value="SDValueInt2","SDTypeInt2","int2",[8,8]
    elif property_id=="$format":kind,typ,ident,value="SDValueEnum","SDTypeEnum","sbs::compositing::format",0
    elif property_id=="$randomseed":kind,typ,ident,value="SDValueInt","SDTypeInt","int",0
    elif property_id=="Disorder":kind,typ,ident,value="SDValueFloat","SDTypeFloat","float",0.0
    elif property_id=="invert":kind,typ,ident,value="SDValueBool","SDTypeBool","bool",True
    else:raise ValueError("Unregistered default property")
    result=dict(class_name=kind,type=dict(class_name=typ,id=ident,modifier=dict(name="Auto",value=0)),value=value)
    if property_id=="$format":result["value_id"]="8_bits_per_channel"
    return result

def _validate_producer(packages,evidence,graph_urls):
    if type(evidence) is not dict or set(evidence)!={"schema_version","literals","xml_bindings"} or type(evidence["schema_version"]) is not int or evidence["schema_version"]!=1:raise ValueError("Invalid producer evidence")
    source=next(p for p in packages if p["role"]=="source");expected=[]
    for graph in source["typed_view"]["graphs"]:
        by_id={n["id"]:n for n in graph["nodes"]}
        bindings=[b for b in evidence["xml_bindings"] if b.get("graph_identifier")==graph["identifier"]]
        if len(bindings)!=1:raise ValueError("Missing/duplicate XML UID binding")
        _equal(bindings[0],dict(package_path=source["path"],package_uid=source["uid"],graph_identifier=graph["identifier"],graph_url=graph_urls[graph["identifier"]],xml_graph_uid=graph["uid"],
            node_outputs=[dict(node_id=n["id"],SDK_output_property_id=n["output"]["id"],xml_output_uid=n["output"]["uid"]) for n in graph["nodes"]],basis="numeric UIDs from copy XML only, linked by canonical package/graph identifier/URL and node/property IDs"),"XML UID binding differs")
        xml=graph_registry._parse(source["copy_xml"]);g=graph_registry._one([g for g in xml.findall("content/graph") if graph_registry._leaf(g,"identifier")==graph["identifier"]],"producer graph")
        for literal in graph["literals"]:
            node_id=None if literal["owner"]=="graph" else literal["owner"];node=None if node_id is None else by_id[node_id]
            role="graph" if node is None else "noise" if node["reference"]["identifier"]=="vertical_noise" else "invert"
            key=(graph["identifier"],node_id,literal["id"]);rows=[e for e in evidence["literals"] if (e.get("owner",{}).get("graph_identifier"),e.get("owner",{}).get("node_id"),e.get("property_id"))==key]
            if len(rows)!=1:raise ValueError("Missing/duplicate producer owner")
            row=rows[0];mask_source.fields(row,{"owner","role","property_id","category","current","default","binding_basis"},"producer literal")
            owner=row["owner"];mask_source.fields(owner,{"package_path","package_uid","graph_identifier","graph_url","node_id","definition"},"producer owner")
            if owner["package_path"]!=source["path"] or owner["package_uid"]!=source["uid"] or owner["graph_identifier"]!=graph["identifier"] or owner["graph_url"]!=graph_urls.get(graph["identifier"]):raise ValueError("Producer package/graph owner differs")
            if owner["definition"]!=("SDSBSCompGraph" if node is None else graph_registry.INSTANCE) or row["role"]!=role or row["category"]!="Input":raise ValueError("Producer definition/category differs")
            _equal(row["default"],_default_value(literal["id"]),"Unapproved literal default wrapper/type/value")
            current=dict(class_name=literal["wrapper"],type=literal["value_type"],value=literal["value"])
            if "value_id" in literal:current["value_id"]=literal["value_id"]
            _equal(row["current"],current,"Current/default wrapper evidence mismatch")
            if row["binding_basis"]!=("strict_copy_XML_no_dynamic" if node is None else "public_node_unbound"):raise ValueError("Unsupported binding evidence")
            if role=="invert" and literal["id"]=="invert":
                n=graph_registry._one([n for n in g.findall("compNodes/compNode") if graph_registry._leaf(n,"uid")==node_id],"Invert owner")
                slots=[p for p in n.findall("compImplementation/compInstance/parameters/parameter") if graph_registry._leaf(p,"name")=="invert"]
                if not slots:
                    # Actual native copy omits the official default True slot.
                    # Exact official stock/fileUID-only binding is still checked
                    # by validate_source immediately after this producer proof.
                    _equal(literal,graph_registry._typed(node_id,"invert","bool",True),"Native sparse Bool requires exact typed unbound Absolute True")
                    _equal(row["current"],row["default"],"Native sparse Bool current must equal the official default True")
                elif len(slots)!=1:raise ValueError("Native sparse Bool has duplicate slots")
            expected.append(key)
    if len(expected)!=len(evidence["literals"]):raise ValueError("Unregistered producer evidence")
    if len(evidence["xml_bindings"])!=len(source["typed_view"]["graphs"]):raise ValueError("Unregistered XML binding")
    _json(evidence)

def _project_literal(observed):
    mask_source.fields(observed,{"owner","role","property_id","category","declaration","declarations","flags","inheritance","function","connections","current","default","binding_basis"},"literal observation")
    _json(observed)
    if observed["category"]!="Input" or observed["function"] is not None or observed["connections"]!=[]:raise ValueError("Observed literal is not unbound Input")
    current=observed["current"]
    projection=dict(owner="graph" if observed["owner"]["node_id"] is None else observed["owner"]["node_id"],id=observed["property_id"],declaration=observed["declaration"],declarations=observed["declarations"],wrapper=current["class_name"],value_type=current["type"],inheritance=observed["inheritance"],function=None,connections=[],value=current["value"],flags=observed["flags"])
    if "value_id" in current:projection["value_id"]=current["value_id"]
    evidence={k:copy.deepcopy(observed[k]) for k in ("owner","role","property_id","category","current","default","binding_basis")}
    return copy.deepcopy(projection),evidence

def _signature(proof,evidence):
    value=dict(schema_version=1,registry_authored_manifest=proof["authored_manifest"],registry_authored_sha256=proof["authored_sha256"],producer_evidence_sha256=mask_source.signature(evidence))
    if mask_source.signature(proof["authored_manifest"])!=proof["authored_sha256"]:raise ValueError("Registry proof hash differs")
    return value,mask_source.signature(value)

def _context(lifetime,authored_sha256):
    return mask_source.context(dict(lifetime,authored_sha256=authored_sha256),historical=True)

def _png(path,expected=None):
    data,digest=maskio.read(path,expected);maskio.decode_black(data)
    if len(data)<33 or struct.unpack(">IIBBBBB",data[16:29])!=(512,512,16,0,0,0,0):raise ValueError("Capture PNG is not512x512 grayscale16")
    offset=8;parts=[]
    while offset<len(data):
        n=struct.unpack(">I",data[offset:offset+4])[0];kind=data[offset+4:offset+8]
        if kind==b"IDAT":parts.append(data[offset+8:offset+8+n])
        offset+=n+12
    inflater=zlib.decompressobj();raw=inflater.decompress(b"".join(parts),512*1025)
    if len(raw)!=512*1025 or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:raise ValueError("Capture PNG inflate differs")
    previous=bytearray(1024);decoded=hashlib.sha256();at=0
    for _ in range(512):
        mode=raw[at];row=bytearray(raw[at+1:at+1025]);at+=1025
        for i in range(1024):
            a=row[i-2] if i>=2 else 0;b=previous[i];c=previous[i-2] if i>=2 else 0
            if mode==0:prediction=0
            elif mode==1:prediction=a
            elif mode==2:prediction=b
            elif mode==3:prediction=(a+b)//2
            else:
                p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c);prediction=a if pa<=pb and pa<=pc else b if pb<=pc else c
            row[i]=(row[i]+prediction)&255
        decoded.update(row);previous=row
    return dict(path=str(path),sha256=digest,decoded_u16be_sha256=decoded.hexdigest(),width=512,height=512,bit_depth=16,format="LUM16",bytes=len(data))

def _save_texture(texture,path):
    """Narrow hook for actual raw-before/PNG/raw-after acceptance instrumentation."""
    texture.save(str(path),"")

def _serialization_base(owned,source_copy):
    # The base comes from this operation's real copy destination, never XML/UI.
    path=logical_path(source_copy["copy_path"])
    if path.parent!=owned.work or str(path)!=source_copy["copy_path"] or not io_path(path).is_file() or source_copy["serialization_base"]!=str(path.parent):raise ValueError("Owned source copy/base mismatch")
    return str(path.parent)


def _copy_stage(runtime,owned,snapshot,label,forbidden,counts):
    packages=[];copy_metadata=[]
    for role in ("source","noise","invert"):
        identities=[i for i in snapshot["identities"] if i["role"]==role]
        if not identities:continue
        identity=identities[0];target=owned.path(label+"-"+role+".sbs")
        if io_path(target).exists():raise FileExistsError("Copy target exists")
        counts["copies"]+=1
        if counts["copies"]>counts["copy_limit"]:raise ValueError("Operation copy limit exceeded")
        runtime.copy(identity,target);raw=owned.read(target)
        owned.evidence(label+"-raw-"+role,dict(role=role,original_identity=identity,copy_path=str(target),serialization_base=str(target.parent),raw_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),status="raw_copy_preserved_before_XML_and_producer_validation"))
        packages.append(dict(role=role,path=identity["path"],uid=identity["uid"],copy_xml=raw,typed_view=None))
        tree=graph_registry._parse(raw)
        copy_metadata.append(dict(role=role,original_identity=identity,copy_path=str(target),serialization_base=str(target.parent),raw_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),
            copy_locator_tokens=[dict(namespace_uid=graph_registry._leaf(d,"uid"),filename=graph_registry._leaf(d,"filename")) for d in tree.findall("dependencies/dependency")]))
        _equal(runtime.state(snapshot["identities"],owned.read),snapshot["protection"],"Original changed during native copy")
    owned.evidence(label+"-copy-locators",dict(copies=copy_metadata,original_context=snapshot["lifetime"],original_locator_tokens=snapshot["original_locator_tokens"]))
    # Collect complete raw/plain views BEFORE validation. Collector preserves partial getter failures.
    projection,evidence=runtime.collect(snapshot,packages,lambda value:owned.evidence(label+"-partial-producer",value))
    owned.evidence(label+"-producer",dict(packages=[dict(role=p["role"],path=p["path"],uid=p["uid"],typed_view=p["typed_view"]) for p in projection],producer=evidence))
    _validate_producer(projection,evidence,snapshot["source_graph_urls"])
    source_copy=graph_registry._one([p for p in copy_metadata if p["role"]=="source"],"owned source copy")
    source_base=_serialization_base(owned,source_copy)
    proof=graph_registry.validate_source(selection=snapshot["selection"],packages=projection,stock_references=runtime.references(owned.read),forbidden_bitmap_paths=forbidden,source_serialization_base=source_base)
    combined,signature=_signature(proof,evidence);owned.evidence(label+"-proof",dict(registry=proof,producer_evidence_sha256=mask_source.signature(evidence),operation_authored_payload=combined,operation_authored_sha256=signature))
    return dict(packages=projection,evidence=evidence,proof=proof,signature=signature,combined=combined,context=_context(snapshot["lifetime"],signature),serialization_base=source_base)

def _operate(*,selection,selected_context,operation_id,owned_directory,forbidden_bitmap_paths,runtime,inspection):
    selected=mask_source.selection(selection,historical=True);operation_id=mask_source.run_id(operation_id)
    if not inspection:prior=mask_source.context(selected_context,historical=True)
    runtime.assert_thread();owned=_Owned(owned_directory,operation_id);counts=dict(copies=0,copy_limit=3 if inspection else 6,compute=0,PNG=0,worker=0);stage="preflight";failure=None;snapshot=None
    try:
        snapshot=runtime.inspect(selected,owned.read)
        owned.evidence("preflight",snapshot)
        if not inspection and any(prior[k]!=snapshot["lifetime"][k] for k in mask_source.CONTEXT-{"authored_sha256"}):raise ValueError(mask_source.RESELECT)
        stage="pre_copy";pre=_copy_stage(runtime,owned,snapshot,"pre",forbidden_bitmap_paths,counts)
        mask_source.require_selection_context(pre["context"],_context(runtime.lifetime(selected),pre["signature"]))
        if not inspection:mask_source.require_selection_context(prior,pre["context"])
        _equal(runtime.state(snapshot["identities"],owned.read),snapshot["protection"],"Original preflight protection differs")
        if inspection:
            # Reobserve typed/default values without an extra copy or compute before adopting context.
            again,evidence=runtime.collect(snapshot,pre["packages"],lambda v:owned.evidence("selection-partial",v))
            owned.evidence("selection-final-producer",dict(packages=[p["typed_view"] for p in again],producer=evidence))
            _equal(evidence,pre["evidence"],"Selection producer changed")
            _equal([p["typed_view"] for p in again],[p["typed_view"] for p in pre["packages"]],"Selection authored projection changed")
            mask_source.require_selection_context(pre["context"],_context(runtime.lifetime(selected),pre["signature"]))
            _equal(runtime.state(snapshot["identities"],owned.read),snapshot["protection"],"Original changed while inspecting selection")
            result=dict(schema_version=1,operation_id=operation_id,selected_context=pre["context"],proof=pre["proof"],operation_authored_payload=pre["combined"],counts=counts,session_marker="host module generation only; not SDK generation",feature_active=False)
        else:
            target=owned.path("terminal.png");evaluator=None
            if io_path(target).exists():raise FileExistsError("PNG target exists")
            renderer=getattr(runtime,"evaluate_copies",None)
            if renderer is not None:
                stage="external_evaluation"
                evaluator=renderer(pre,selected,owned,target,counts)
                counts["PNG"]+=1;png=_png(target)
                _equal(evaluator["output_png_sha256"],png["sha256"],"Evaluator/output PNG binding differs")
                owned.evidence("evaluator",evaluator)
            else:
                # Pure replay runtimes retain their existing compute/save protocol.
                stage="compute";counts["compute"]+=1;runtime.compute(selected)
                stage="save_terminal";runtime.save(selected,target);counts["PNG"]+=1;png=_png(target)
            stage="postflight";post_snapshot=runtime.inspect(selected,owned.read)
            owned.evidence("postflight",post_snapshot);_equal(post_snapshot,snapshot,"Original context/protection changed after compute")
            post=_copy_stage(runtime,owned,post_snapshot,"post",forbidden_bitmap_paths,counts)
            mask_source.require_operation_context(pre["context"],post["context"]);_equal(pre["combined"],post["combined"],"Operation authored proof changed")
            _equal(runtime.state(snapshot["identities"],owned.read),snapshot["protection"],"Original changed after capture")
            _equal(_png(target,png["sha256"]),png,"PNG changed after postflight")
            source=next(r for r in snapshot["protection"]["packages"] if r["role"]=="source")
            capture_values=dict(designer_version=snapshot["designer_version"],selection=selected,context=post["context"],pre_authored_sha256=pre["signature"],post_authored_sha256=post["signature"],package_modified=source["modified"],disk_file_sha256=source["disk_sha256"],captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
            if evaluator is not None:capture_values["evaluator"]=evaluator
            capture=mask_source.capture(capture_values,historical=True)
            result=dict(schema_version=1,operation_id=operation_id,png=png,capture=capture,proof=post["proof"],operation_authored_payload=post["combined"],producer_evidence_sha256=mask_source.signature(post["evidence"]),counts=counts,feature_active=False)
        result["evidence"]=copy.deepcopy(owned.refs);owned.evidence("handoff",result);return copy.deepcopy(result)
    except runtime.errors as error:
        failure=dict(status="failed",stage=stage,operation_id=operation_id,error_class=type(error).__name__,error=str(error),counts=copy.deepcopy(counts),work_directory=str(owned.work),evidence=copy.deepcopy(owned.refs))
        try:
            if snapshot is not None:_equal(runtime.state(snapshot["identities"],owned.read),snapshot["protection"],"Original preservation failed after error")
            failure["original_protection_equal"]=snapshot is not None
        except runtime.errors as preservation:failure["original_protection_equal"]=False;failure["preservation_error"]=dict(class_name=type(preservation).__name__,error=str(preservation));preservation.__traceback__=None
        failure["failure_artifact"]=owned.failure(stage,operation_id,error);error.__traceback__=None;error.__cause__=None;error.__context__=None
    # Outside the native exception handler: no SDK exception/traceback wrapper chain escapes.
    raise CaptureError(failure) from None

def capture_terminal(selection,selected_context,operation_id,owned_directory,forbidden_bitmap_paths):
    from .evaluation import evaluation_scope
    with evaluation_scope():
        return _operate(selection=selection,selected_context=selected_context,operation_id=operation_id,owned_directory=owned_directory,forbidden_bitmap_paths=forbidden_bitmap_paths,runtime=_SDK(),inspection=False)

def inspect_terminal_selection(selection,operation_id,owned_directory,forbidden_bitmap_paths):
    return _operate(selection=selection,selected_context=None,operation_id=operation_id,owned_directory=owned_directory,forbidden_bitmap_paths=forbidden_bitmap_paths,runtime=_SDK(),inspection=True)

class _SDK:
    """Each method obtains fresh canonical wrappers and returns data only."""
    @property
    def errors(self):
        from sd.api.apiexception import APIException
        return Exception,APIException
    def assert_thread(self):
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance()
        if app is None or QThread.currentThread()!=app.thread():raise ValueError("Terminal adapter requires Designer UI thread")
    def _manager(self):
        import sd
        return sd.getContext().getSDApplication().getPackageMgr()
    def evaluate_copies(self,pre,selected,owned,target,counts):
        import sd
        from sd.api.sdapplication import SDApplicationPath
        from . import deterministic_renderer
        installation=sd.getContext().getSDApplication().getPath(SDApplicationPath.InstallationDir)
        if not installation:raise ValueError("Designer installation directory unavailable")
        counts.update(cook=0,render=0)
        def attempt(name):
            if name not in ("cook","render") or counts[name]!=0:raise ValueError("Fixed evaluator child budget exhausted")
            counts[name]+=1
            owned.evidence("evaluator-"+name+"-attempt",dict(kind=name,attempt=counts[name],SDK_compute=counts["compute"],backend="designer_cli_d3d11_cpu1"))
        return deterministic_renderer.render(packages=pre["packages"],serialization_base=pre["serialization_base"],selection=selected,installation=installation,work=owned.work,target=target,attempt=attempt,evidence=owned.evidence)
    def _identity(self,package):
        value=package.getFilePath()
        return dict(path=None if not value else str(logical_path(value)),uid=mask_source.package_uid(str(package.getUID())))
    def _packages(self,manager):
        values=manager.getPackages()
        if values is None or len(values)>4096:raise ValueError("Loaded package budget")
        return list(values)
    def _canonical(self,manager,identity,user=False):
        packages=self._packages(manager);matches=[p for p in packages if self._identity(p)["uid"]==identity["uid"]]
        if len(matches)!=1 or self._identity(matches[0])!={k:identity[k] for k in ("path","uid")}:raise ValueError(mask_source.RESELECT)
        if user:
            users=manager.getUserPackages()
            if users is None or len(users)>4096 or len([p for p in users if self._identity(p)==self._identity(matches[0])])!=1:raise ValueError("Source is not unique editable user package")
        return matches[0]
    def _inventory(self,manager):
        return mask_source.inventory([dict(package_path=self._identity(p)["path"],package_uid=self._identity(p)["uid"]) for p in self._packages(manager)])
    def _graphs(self,package,source=False):
        from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
        values=package.getChildrenResources(False)
        if values is None or len(values)>2 or any(type(r) is not SDSBSCompGraph or r.getClassName()!="SDSBSCompGraph" for r in values):raise ValueError("Closed comp graph inventory required")
        rows=list(values);ids=[g.getIdentifier() for g in rows]
        if len(ids)!=len(set(ids)) or not rows:raise ValueError("Graph identity missing/duplicate")
        return rows
    def _selected(self,manager,selected):
        from sd.api.sdproperty import SDPropertyCategory as C
        package=self._canonical(manager,dict(path=selected["package_path"],uid=selected["package_uid"]),True)
        g=graph_registry._one([g for g in self._graphs(package,True) if g.getIdentifier()==selected["graph_identifier"]],"selected graph")
        outputs=g.getOutputNodes()
        if outputs is None or len(outputs)>1:raise ValueError("Source requires unique terminal")
        matches=[]
        for n in outputs:
            if n.getDefinition().getId()!="sbs::compositing::output":raise ValueError("Selected output is not terminal")
            p=n.getPropertyFromId("identifier",C.Annotation)
            if p is None or [self._type(t) for t in p.getTypes()]!=[dict(class_name="SDTypeString",id="string",modifier=dict(name="Auto",value=0))] or n.getPropertyGraph(p) is not None or list(n.getPropertyConnections(p)):raise ValueError("Terminal annotation is not known unbound String")
            value=n.getPropertyValue(p)
            if value is None or value.getClassName()!="SDValueString":raise ValueError("Terminal identifier annotation unavailable")
            if value.get()==selected["terminal_identifier"]:matches.append(n)
        n=graph_registry._one(matches,"canonical selected terminal");props=n.getProperties(C.Output)
        if props is None or len(props)!=1 or props[0].getId()!=selected["terminal_identifier"]:raise ValueError("Terminal Output identity differs")
        return package,g,n,props[0]
    def lifetime(self,selected):
        manager=self._manager();package,g,n,p=self._selected(manager,selected)
        return dict(selected,graph_url=g.getUrl(),terminal_node_id=n.getIdentifier(),output_id=p.getId(),session_token=_SESSION_TOKEN,loaded_inventory_sha256=mask_source.signature(self._inventory(manager)))
    def state(self,identities,read):
        manager=self._manager();rows=[]
        for identity in identities:
            p=self._canonical(manager,identity,identity["role"]=="source");raw=read(identity["path"]);modified=p.isModified()
            if type(modified) is not bool:raise ValueError("Package modified is not bool")
            rows.append(dict(role=identity["role"],identity=self._identity(p),modified=modified,disk_sha256=hashlib.sha256(raw).hexdigest(),disk_bytes=len(raw)))
        return dict(packages=rows,inventory=self._inventory(manager))
    def _scan(self,manager,identities):
        from sd.api.sdgraph import SDGraph
        from sd.api.sdproperty import SDPropertyCategory as C
        counts=dict(resources=0,nodes=0,edges=0,properties=0,function_FX=0,function_nodes=0,string_bytes=0);seen=set();active=set();edges=set()
        caps=dict(resources=24,nodes=96,edges=128,properties=768,function_FX=20,function_nodes=128,string_bytes=1024*1024)
        def add(key,count=1):
            counts[key]+=count
            if counts[key]>caps[key]:raise ValueError("Public preflight budget: "+key)
        def text(value):
            if type(value) is not str or len(value.encode("utf-8"))>16384:raise ValueError("Public metadata string budget")
            add("string_bytes",len(value.encode("utf-8")))
        def visit(resource,identity,locator,depth):
            if depth>64 or not isinstance(resource,SDGraph) or resource.getClassName() not in {"SDSBSCompGraph","SDSBSFxMapGraph","SDSBSFunctionGraph"}:raise ValueError("Unknown/embedded resource before copy")
            package=resource.getPackage()
            if package is not None and self._identity(package)!=identity:raise ValueError("Resource escaped owned closure")
            url=resource.getUrl();identifier=resource.getIdentifier();text(url);text(identifier)
            key=(identity["uid"],resource.getClassName(),url or locator,identifier)
            if key in active:raise ValueError("Source feedback/cycle before copy")
            if key in seen:return
            active.add(key);seen.add(key);add("resources")
            if resource.getClassName()!="SDSBSCompGraph":add("function_FX")
            for category in (C.Input,C.Output,C.Annotation):
                props=resource.getProperties(category)
                if props is None or len(props)>768:raise ValueError("Resource property budget before copy")
                add("properties",len(props))
                for p in props:text(p.getId());text(p.getLabel());text(p.getDescription())
            metadata=resource.getMetadataDict()
            if metadata is not None:
                props=metadata.getProperties()
                if props is None or len(props)>768:raise ValueError("Metadata property budget")
                for prop in props:
                    add("properties");text(prop.getId());value=metadata.getPropertyValue(prop)
                    if value is None or value.getClassName()!="SDValueString":raise ValueError("Unknown/opaque metadata before copy")
                    text(value.get())
            nodes=resource.getNodes()
            if nodes is None or len(nodes)>96:raise ValueError("Node budget before copy")
            add("nodes",len(nodes))
            if resource.getClassName()=="SDSBSFunctionGraph":add("function_nodes",len(nodes))
            for node in nodes:
                text(node.getIdentifier());text(node.getDefinition().getId())
                if identity["uid"]!=identities[0]["uid"] and node.getDefinition().getId() not in _STOCK_DEFINITIONS:raise ValueError("Unknown stock node definition before copy")
                for category in (C.Input,C.Output,C.Annotation):
                    props=node.getProperties(category)
                    if props is None or len(props)>768:raise ValueError("Property budget before copy")
                    add("properties",len(props))
                    for p in props:
                        text(p.getId());text(p.getLabel());text(p.getDescription());links=node.getPropertyConnections(p)
                        if links is None or len(links)>128:raise ValueError("Connection budget before copy")
                        for link in links:
                            ends=[(link.getInputPropertyNode().getIdentifier(),link.getInputProperty().getId(),link.getInputProperty().getCategory().name),(link.getOutputPropertyNode().getIdentifier(),link.getOutputProperty().getId(),link.getOutputProperty().getCategory().name)]
                            if {e[2] for e in ends}!={"Input","Output"}:raise ValueError("Unknown connection getter orientation")
                            edge=(key,tuple(sorted(ends)))
                            if edge not in edges:edges.add(edge);add("edges")
                        fn=node.getPropertyGraph(p)
                        if fn is not None:visit(fn,identity,locator+"/"+node.getIdentifier()+"/"+category.name+":"+p.getId(),depth+1)
                ref=node.getReferencedResource()
                if ref is not None:
                    target=ref.getPackage()
                    target_identity=identity if target is None else self._identity(target)
                    if target_identity not in [{k:r[k] for k in ("path","uid")} for r in identities]:raise ValueError("Unknown dependency before copy")
                    visit(ref,target_identity,locator+"/"+node.getIdentifier()+"/referenced",depth+1)
            active.remove(key)
        for identity in identities:
            p=self._canonical(manager,identity,identity["role"]=="source")
            for g in self._graphs(p):visit(g,{k:identity[k] for k in ("path","uid")},identity["role"]+"/"+g.getIdentifier(),0)
        return counts
    def inspect(self,selected,read):
        import sd
        manager=self._manager();source,g,n,p=self._selected(manager,selected);graphs=self._graphs(source,True);total=0;roles={"source":dict(role="source",**self._identity(source))}
        from sd.api.sdproperty import SDPropertyCategory as C
        reference_bindings=[]
        for graph in graphs:
            nodes=graph.getNodes();total+=len(nodes)
            if len(nodes) not in (2,3) or total>5:raise ValueError("Source graph/node preflight bound")
            for node in nodes:
                definition=node.getDefinition().getId()
                if definition==graph_registry.INSTANCE:
                    ref=node.getReferencedResource()
                    if ref is None or ref.getClassName()!="SDSBSCompGraph" or ref.getIdentifier() not in ("vertical_noise","invert_grayscale"):raise ValueError("Unknown/scatter/bitmap source reference")
                    role="noise" if ref.getIdentifier()=="vertical_noise" else "invert";identity=dict(role=role,**self._identity(ref.getPackage()))
                    self._canonical(manager,identity)
                    if role in roles and roles[role]!=identity:raise ValueError("Multiple package identities for role")
                    roles[role]=identity
                    reference_bindings.append(dict(graph_identifier=graph.getIdentifier(),graph_url=graph.getUrl(),node_id=node.getIdentifier(),definition=definition,referenced_package={k:identity[k] for k in ("path","uid")},referenced_identifier=ref.getIdentifier(),referenced_URL=ref.getUrl()))
                elif definition!="sbs::compositing::output":raise ValueError("Unknown source definition")
            for category in (C.Input,C.Output,C.Annotation):
                props=graph.getProperties(category)
                if props is None or len(props)>768:raise ValueError("Source resource property budget")
        if "noise" not in roles:raise ValueError("Noise source missing")
        identities=[roles[k] for k in ("source","noise","invert") if k in roles]
        for identity in identities:
            package=self._canonical(manager,identity,identity["role"]=="source")
            actual={r.getIdentifier() for r in self._graphs(package)}
            if identity["role"]!="source" and actual!=graph_registry.GRAPH_SETS[identity["role"]]:raise ValueError("Full stock graph inventory differs")
            deps=package.getDependencies()
            if deps is None or len(deps)!=(len(identities)-1 if identity["role"]=="source" else 0):raise ValueError("Non-exact package dependency closure")
            for dep in deps:
                target=dep.getPackage()
                if target is None or self._identity(target) not in [{k:r[k] for k in ("path","uid")} for r in identities if r["role"]!="source"]:raise ValueError("Unowned dependency")
        protection=self.state(identities,read);tokens={}
        for identity in identities:
            xml=graph_registry._parse(read(identity["path"]));tokens[identity["role"]]=[graph_registry._leaf(d,"filename") for d in xml.findall("dependencies/dependency")]
        return dict(selection=selected,identities=identities,protection=protection,lifetime=self.lifetime(selected),source_graph_urls={r.getIdentifier():r.getUrl() for r in graphs},
            original_locator_tokens=tokens,reference_bindings=reference_bindings,public_caps=self._scan(manager,identities),designer_version=sd.getContext().getSDApplication().getVersion())
    def copy(self,identity,target):
        manager=self._manager();package=self._canonical(manager,identity,identity["role"]=="source")
        if io_path(target).exists():raise FileExistsError("Reserved copy destination exists")
        manager.saveCopyOfPackageAs(package,str(target))
    def references(self,read):
        import sd
        from sd.api.sdapplication import SDApplicationPath
        directory=Path(sd.getContext().getSDApplication().getPath(SDApplicationPath.DefaultResourcesDir))/"packages"
        return dict(noise=read(directory/"vertical_noise.sbs"),invert=read(directory/"invert.sbs"))
    def _type(self,t):
        if t is None:raise ValueError("Missing SDK type")
        mod=t.getModifier();return dict(class_name=t.getClassName(),id=t.getId(),modifier=dict(name=mod.name,value=mod.value))
    def _value(self,value):
        if value is None:raise ValueError("Required SDK value/default unavailable")
        name=value.getClassName()
        allowed={"SDValueInt","SDValueInt2","SDValueFloat","SDValueBool","SDValueEnum"}
        if type(value).__name__!=name or name not in allowed:raise ValueError("Unregistered literal wrapper; image/opaque getter forbidden")
        typ=self._type(value.getType());raw=value.get()
        if name=="SDValueInt2":
            raw=[raw.x,raw.y]
            if any(type(v) is not int for v in raw):raise ValueError("Int2 component type differs")
        elif name in ("SDValueInt","SDValueEnum") and type(raw) is not int:raise ValueError("Integer wrapper differs")
        elif name=="SDValueBool" and type(raw) is not bool:raise ValueError("Bool wrapper differs")
        elif name=="SDValueFloat":graph_registry._float32(str(raw),raw)
        result=dict(class_name=name,type=typ,value=raw)
        if name=="SDValueEnum":result["value_id"]=value.getValueId()
        return result
    def _image(self,node,prop):
        if prop is None:raise ValueError("Image endpoint missing")
        return dict(id=prop.getId(),category=prop.getCategory().name,declarations=[self._type(t) for t in prop.getTypes()],flags=dict(connectable=prop.isConnectable(),read_only=prop.isReadOnly(),variadic=prop.isVariadic(),primary=prop.isPrimary(),function_only=prop.isFunctionOnly()),function=None if node.getPropertyGraph(prop) is None else "unsupported_function")
    def _literal(self,package,graph,node,property_id,role):
        from sd.api.sdproperty import SDPropertyCategory as C
        owner=graph if node is None else node;prop=owner.getPropertyFromId(property_id,C.Input)
        if prop is None or prop.getCategory()!=C.Input:raise ValueError("Literal Input missing")
        if node is not None and (node.getPropertyGraph(prop) is not None or list(node.getPropertyConnections(prop))):raise ValueError("Literal is function-bound/connected")
        identity=self._identity(package)
        owner_record=dict(package_path=identity["path"],package_uid=identity["uid"],graph_identifier=graph.getIdentifier(),graph_url=graph.getUrl(),node_id=None if node is None else node.getIdentifier(),definition=graph.getClassName() if node is None else node.getDefinition().getId())
        self._partial_literal=dict(owner=owner_record,property_id=property_id,role=role,status="reading_current")
        current=self._value(owner.getPropertyValue(prop));self._partial_literal.update(current_observed=copy.deepcopy(current),status="reading_default")
        default=self._value(prop.getDefaultValue());types=[self._type(t) for t in prop.getTypes()]
        inheritance=owner.getPropertyInheritanceMethod(prop)
        observed=dict(owner=owner_record,
            role=role,property_id=property_id,category="Input",current=current,default=default,binding_basis="strict_copy_XML_no_dynamic" if node is None else "public_node_unbound",declaration=self._type(prop.getType()),declarations=types,
            inheritance=dict(name=inheritance.name,value=inheritance.value),function=None,connections=[],flags=dict(connectable=prop.isConnectable(),read_only=prop.isReadOnly(),variadic=prop.isVariadic(),primary=prop.isPrimary(),function_only=prop.isFunctionOnly()))
        result=_project_literal(observed);self._partial_literal=dict(status="last_literal_completed");return result
    def collect(self,snapshot,packages,partial):
        from sd.api.sdproperty import SDPropertyCategory as C
        result=copy.deepcopy(packages);evidence=dict(schema_version=1,literals=[],xml_bindings=[])
        try:
            manager=self._manager()
            for package_row in result:
                package=self._canonical(manager,package_row,package_row["role"]=="source");graphs=self._graphs(package)
                if package_row["role"]!="source":
                    package_row["typed_view"]=dict(package_uid=package_row["uid"],graphs=[dict(identifier=g.getIdentifier(),class_name=g.getClassName()) for g in graphs]);continue
                xml=graph_registry._parse(package_row["copy_xml"]);views=[]
                for g in graphs:
                    xg=graph_registry._one([x for x in xml.findall("content/graph") if graph_registry._leaf(x,"identifier")==g.getIdentifier()],"copy source graph")
                    # Root current getters are reached only after this direct authored XML gate.
                    if xg.findall("baseParameters//dynamicValue") or xg.findall("paraminputs") or {graph_registry._leaf(p,"name") for p in xg.findall("baseParameters/parameter")}!={"outputsize","format","randomseed"}:raise ValueError("Unknown/dynamic source base; root current getters forbidden")
                    graph_registry._params(xg,"baseParameters/parameter","graph","graph")
                    literal=[];nodes=[];edges=[];terminal=None
                    for prop_id in _COMMON:
                        p,e=self._literal(package,g,None,prop_id,"graph");literal.append(p);evidence["literals"].append(e)
                    sdk_nodes=g.getNodes();xnodes=xg.findall("compNodes/compNode")
                    if {n.getIdentifier() for n in sdk_nodes}!={graph_registry._leaf(n,"uid") for n in xnodes}:raise ValueError("SDK/XML node inventory differs")
                    seen_edges=set()
                    for xn in xnodes:
                        uid=graph_registry._leaf(xn,"uid");n=g.getNodeFromId(uid)
                        if n is None or n.getIdentifier()!=uid:raise ValueError("Canonical node missing in owner graph")
                        definition=n.getDefinition().getId();outputs=list(n.getProperties(C.Output))
                        if len(outputs)!=1:raise ValueError("Unique image Output required")
                        output=self._image(n,outputs[0]);inputs=[]
                        if definition==graph_registry.INSTANCE:
                            ref=n.getReferencedResource();identity=self._identity(ref.getPackage());canonical=self._canonical(manager,identity)
                            canonical_graph=graph_registry._one([r for r in self._graphs(canonical) if r.getIdentifier()==ref.getIdentifier()],"reference graph")
                            if canonical_graph.getUrl()!=ref.getUrl():raise ValueError("Current canonical resource URL mismatch")
                            role="noise" if ref.getIdentifier()=="vertical_noise" else "invert" if ref.getIdentifier()=="invert_grayscale" else None
                            if role is None:raise ValueError("Unknown source instance")
                            expected=next(i for i in snapshot["identities"] if i["role"]==role)
                            _equal(identity,{k:expected[k] for k in ("path","uid")},"Reference package binding changed")
                            reference=dict(package_uid=identity["uid"],package_path=identity["path"],identifier=ref.getIdentifier());output["uid"]=graph_registry._leaf(xn,"compOutputs/compOutput/uid")
                            if role=="invert":inputs=[self._image(n,n.getPropertyFromId("Source",C.Input))]
                            for prop_id in (*_COMMON,"Disorder" if role=="noise" else "invert"):
                                p,e=self._literal(package,g,n,prop_id,role);literal.append(p);evidence["literals"].append(e)
                            # SDK values stay observed; only owner-ID keyed presentation order follows authored XML.
                            owner_literals=[p for p in literal if p["owner"]==uid];names=[graph_registry._leaf(p,"name") for p in xn.findall("compImplementation/compInstance/parameters/parameter")]
                            ordered=["$"+name if name in ("outputsize","format","randomseed") else name for name in names]
                            ordered += [p["id"] for p in owner_literals if p["id"] not in ordered]
                            literal=[p for p in literal if p["owner"]!=uid]+[graph_registry._one([p for p in owner_literals if p["id"]==name],"observed literal ID") for name in ordered]
                        elif definition=="sbs::compositing::output":
                            reference=None;inputs=[self._image(n,n.getPropertyFromId("inputNodeOutput",C.Input))];out_id=outputs[0].getId()
                            output["uid"]=graph_registry._leaf(xn,"compImplementation/compOutputBridge/output")
                            terminal=dict(node_id=uid,identifier=out_id,output_id=out_id,category="Output",declarations=output["declarations"])
                        else:raise ValueError("Unknown source node")
                        nodes.append(dict(id=uid,definition=definition,reference=reference,inputs=inputs,output=output))
                        for prop in n.getProperties(C.Input):
                            for link in n.getPropertyConnections(prop):
                                ends=[(link.getInputPropertyNode(),link.getInputProperty()),(link.getOutputPropertyNode(),link.getOutputProperty())]
                                source=graph_registry._one([(a,b) for a,b in ends if b.getCategory()==C.Output],"source Output endpoint");dest=graph_registry._one([(a,b) for a,b in ends if b.getCategory()==C.Input],"destination Input endpoint")
                                if dest[0].getIdentifier()!=uid or dest[1].getId()!=prop.getId() or g.getNodeFromId(source[0].getIdentifier()) is None:raise ValueError("Owner-scoped endpoint mismatch")
                                key=(source[0].getIdentifier(),source[1].getId(),uid,prop.getId())
                                if key in seen_edges:raise ValueError("Duplicate canonical edge")
                                seen_edges.add(key);edges.append(list(key))
                    if terminal is None:raise ValueError("Terminal missing")
                    evidence["xml_bindings"].append(dict(package_path=package_row["path"],package_uid=package_row["uid"],graph_identifier=g.getIdentifier(),graph_url=g.getUrl(),xml_graph_uid=graph_registry._leaf(xg,"uid"),
                        node_outputs=[dict(node_id=n["id"],SDK_output_property_id=n["output"]["id"],xml_output_uid=n["output"]["uid"]) for n in nodes],basis="numeric UIDs from copy XML only, linked by canonical package/graph identifier/URL and node/property IDs"))
                    views.append(dict(identifier=g.getIdentifier(),uid=graph_registry._leaf(xg,"uid"),nodes=nodes,literals=literal,edges=edges,terminal=terminal))
                package_row["typed_view"]=dict(package_uid=package_row["uid"],graphs=views)
            _json(evidence);return result,evidence
        except self.errors as error:
            partial(dict(status="producer_getter_failed",evidence=evidence,last_literal=getattr(self,"_partial_literal",dict(status="no_literal_getter_started")),error=dict(class_name=type(error).__name__,message=str(error)[:512])));raise
    def compute(self,selected):
        from .evaluation import compute_graph
        manager=self._manager();package,graph,node,prop=self._selected(manager,selected);compute_graph(graph)
    def save(self,selected,path):
        from sd.api.sdvaluetexture import SDValueTexture
        from sd.api.sdtexture import SDTexture,SBSPixelFormat
        manager=self._manager();package,graph,node,prop=self._selected(manager,selected)
        value=node.getPropertyValue(prop)
        if type(value) is not SDValueTexture or value.getClassName()!="SDValueTexture" or self._type(value.getType())!=dict(class_name="SDTypeCustom",id="SDTexture",modifier=dict(name="Auto",value=0)):raise ValueError("Current texture value type differs from measured SDTypeCustom/SDTexture")
        texture=value.get()
        if not isinstance(texture,SDTexture):raise ValueError("Current terminal lacks SDTexture")
        size=texture.getSize()
        if [size.x,size.y]!=[512,512] or texture.getBytesPerPixel()!=2 or texture.getPixelFormat()!=SBSPixelFormat.LUM16:raise ValueError("Current terminal must be512x512LUM16/bpp2")
        _save_texture(texture,path)
