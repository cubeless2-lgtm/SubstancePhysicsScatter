"""Inactive, value-only closed registry for two graph-terminal topologies.

No SDK/file access occurs in validate_source. A future adapter must produce the
documented typed projection from canonical live objects; this is not that adapter.
Native serializer variations beyond exact stock fileUID substitution are gated.
"""
from __future__ import annotations
import copy,ctypes,hashlib,json,math,re,struct
from xml.etree import ElementTree as ET
from xml.parsers import expat
from . import mask_source

STOCK_SHA={"noise":"47116c37a2e0d59dfc149760d1b999f19323272e23d3164af01da918b0112cc4","invert":"edc847dccbdb21d2ec745647dfd60c2957f251c60f3252162238fa6b881b7c11"}
GRAPH_SETS={"noise":{"vertical_noise"},"invert":{"invert","invert_grayscale"}}
INSTANCE="sbs::compositing::sbscompgraph_instance"
LIMITS=dict(xml_file=2*1024*1024,xml_total=12*1024*1024,json_file=1024*1024,json_total=8*1024*1024,depth=64,string=16384,text=1024*1024,source_graphs=2,source_nodes=5)

def _fields(value,keys,label):
    if type(value) is not dict or set(value)!=set(keys):raise ValueError("Invalid "+label+" fields")
    return value

def _plain(value,depth=0):
    if depth>64:raise ValueError("Typed JSON depth exceeded")
    if type(value) in (type(None),bool,int):return
    if type(value) is float:
        if not math.isfinite(value):raise ValueError("Non-finite typed value")
        return
    if type(value) is str:
        if len(value.encode("utf-8"))>LIMITS["string"] or "\0" in value:raise ValueError("Typed string budget/character")
        return
    if type(value) is list:
        for item in value:_plain(item,depth+1)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for key,item in value.items():_plain(key,depth+1);_plain(item,depth+1)
        return
    raise ValueError("Opaque/non-JSON typed input")

def _json(value):
    _plain(value);raw=json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if len(raw)>LIMITS["json_file"]:raise ValueError("Typed JSON file budget exceeded")
    return raw

def _same(actual,expected,label):
    # bool/int and -0/+0 must not collapse through Python equality.
    if type(actual) is not type(expected):raise ValueError("Typed mismatch: "+label)
    if type(expected) is dict:
        if set(actual)!=set(expected):raise ValueError("Unknown/missing typed field: "+label)
        for key in expected:_same(actual[key],expected[key],label+"/"+key)
    elif type(expected) is list:
        if len(actual)!=len(expected):raise ValueError("Typed list mismatch: "+label)
        for a,b in zip(actual,expected):_same(a,b,label)
    elif type(expected) is float:
        if struct.pack("=d",actual)!=struct.pack("=d",expected):raise ValueError("Typed float mismatch: "+label)
    elif actual!=expected:raise ValueError("Typed value mismatch: "+label)

def _float32(token,sdk_value):
    """Only declared Float/FloatN literal components; preserves signed zero."""
    if type(token) is not str or type(sdk_value) is not float or not math.isfinite(sdk_value):raise ValueError("Expected finite Float32 literal")
    if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",token):raise ValueError("Unsupported XML Float32 spelling")
    try:number=float(token)
    except ValueError as error:raise ValueError("Invalid XML Float32 token") from error
    if not math.isfinite(number):raise ValueError("Non-finite XML Float32")
    c=ctypes.c_float(number).value
    if not math.isfinite(c) or struct.pack("=d",ctypes.c_float(sdk_value).value)!=struct.pack("=d",sdk_value):raise ValueError("SDK value is not exact binary32")
    if struct.pack("=f",c)!=struct.pack("=f",sdk_value):raise ValueError("Float32 bit mismatch")
    return struct.pack("=f",c).hex()

def _parse(raw):
    if type(raw) is not bytes or not 0<len(raw)<=LIMITS["xml_file"]:raise ValueError("XML bytes/file budget")
    text=raw.removeprefix(b"\xef\xbb\xbf").decode("utf-8",errors="strict")
    if "\0" in text or text.startswith("\ufeff") or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():raise ValueError("XML encoding/DTD/entity forbidden")
    declaration=re.match(r"\A<\?xml\s.*?\?>",text,re.DOTALL)
    if declaration:
        enc=re.findall(r"\bencoding\s*=\s*(['\"])(.*?)\1",declaration.group(),re.I)
        if len(enc)>1 or any(v.lower()!="utf-8" for _,v in enc):raise ValueError("Only UTF8 XML")
    try:root=ET.fromstring(raw,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
    except ET.ParseError as error:raise ValueError("Invalid SBS XML") from error
    total=0
    def visit(node,depth):
        nonlocal total
        if depth>LIMITS["depth"] or not isinstance(node.tag,str) or "{" in node.tag or ":" in node.tag:raise ValueError("XML depth/namespace")
        if node.text and node.text.strip() or node.tail and node.tail.strip():raise ValueError("Unknown XML text payload")
        for key,value in node.attrib.items():
            size=len(value.encode("utf-8"));total+=size
            if key!="v" or size>LIMITS["string"]:raise ValueError("Unknown XML attribute/string budget")
        if total>LIMITS["text"]:raise ValueError("XML text budget")
        for child in node:visit(child,depth+1)
    visit(root,0)
    if root.tag!="package":raise ValueError("Expected SBS package")
    return root

def _one(values,label):
    values=list(values)
    if len(values)!=1:raise ValueError("Missing/duplicate "+label)
    return values[0]

def _leaf(node,path):
    item=_one(node.findall(path),path)
    if list(item) or set(item.attrib)!={"v"}:raise ValueError("Invalid scalar "+path)
    return item.attrib["v"]

def _children(node,names,repeated=()):
    if node.attrib:raise ValueError("Unknown container attribute")
    tags=[n.tag for n in node]
    if set(tags)!=set(names) or any(tags.count(t)!=1 for t in names if t not in repeated):raise ValueError("Unknown/missing/duplicate XML structure: "+node.tag)

def _uid(token):
    if not re.fullmatch(r"[1-9][0-9]{0,19}",token):raise ValueError("Non-canonical numeric UID")
    return token

def _top_span(raw):
    stack=[];found=[];parser=expat.ParserCreate()
    def start(name,attrs):
        if stack==["package"] and name=="fileUID":found.append((parser.CurrentByteIndex,attrs))
        stack.append(name)
    parser.StartElementHandler=start;parser.EndElementHandler=lambda name:stack.pop();parser.Parse(raw,True)
    offset,attrs=_one(found,"package fileUID")
    if set(attrs)!={"v"}:raise ValueError("Invalid fileUID scalar")
    end=raw.index(b">",offset)+1;match=re.search(rb'\bv="([^"]*)"',raw[offset:end])
    if match is None:raise ValueError("Unsupported fileUID serialization")
    return offset+match.start(1),offset+match.end(1)

def _stock(role,package,reference):
    if type(reference) is not bytes or not 0<len(reference)<=LIMITS["xml_file"] or hashlib.sha256(reference).hexdigest()!=STOCK_SHA[role]:raise ValueError("Official stock SHA mismatch")
    original=_parse(reference);root=_parse(package["copy_xml"])
    value=_leaf(root,"fileUID")
    if mask_source.package_uid(value)!=package["uid"]:raise ValueError("Stock package UID mismatch")
    a,b=_top_span(reference)
    # Native serialization variations remain unsupported pending explicit raw proof.
    if reference[:a]+value.encode("ascii")+reference[b:]!=package["copy_xml"]:raise ValueError("Stock must match exact official bytes/fileUID-only mapping; native copy form unproven")
    graphs=root.findall("content/graph");ids=[_leaf(g,"identifier") for g in graphs]
    if len(ids)!=len(set(ids)) or set(ids)!=GRAPH_SETS[role]:raise ValueError("Stock complete graph inventory mismatch")
    expected=dict(package_uid=package["uid"],graphs=[dict(identifier=ident,class_name="SDSBSCompGraph") for ident in ids])
    _same(package["typed_view"],expected,"stock typed graph inventory")
    return dict(role=role,package_uid=package["uid"],official_sha256=STOCK_SHA[role],copy_sha256=hashlib.sha256(package["copy_xml"]).hexdigest(),
        original_file_uid=mask_source.package_uid(_leaf(original,"fileUID")),file_uid_only=True,graphs=ids)

def _typed(owner,name,kind,value):
    spec={"int2":("SDTypeInt2","int2","SDValueInt2"),"int":("SDTypeInt","int","SDValueInt"),"format":("SDTypeEnum","sbs::compositing::format","SDValueEnum"),"float":("SDTypeFloat","float","SDValueFloat"),"bool":("SDTypeBool","bool","SDValueBool")}[kind]
    result=dict(owner=owner,id=name,declaration=dict(class_name=spec[0],id=spec[1],modifier=dict(name="Auto",value=0)),wrapper=spec[2],inheritance=dict(name="Absolute",value=2),function=None,connections=[],value=value)
    result["declarations"]=[copy.deepcopy(result["declaration"])]
    if kind=="format":result["declarations"].append(dict(class_name="SDTypeInt",id="int",modifier=dict(name="Auto",value=0)))
    result["value_type"]=copy.deepcopy(result["declaration"])
    result["flags"]={name:False for name in ("connectable","read_only","variadic","primary","function_only")}
    if kind=="format":result["value_id"]="16_bits_per_channel"
    return result

def _params(parent,path,owner,kind):
    rows=parent.findall(path);names=[_leaf(p,"name") for p in rows]
    allowed={"outputsize","format","randomseed"}|({"Disorder"} if kind=="noise" else {"invert"} if kind=="invert" else set())
    if len(names)!=len(set(names)) or not {"outputsize","format","randomseed"}<=set(names) or not set(names)<=allowed:raise ValueError("Unknown/missing source parameter (dynamic graph-base unsupported)")
    expected={"outputsize":("constantValueInt2","9 9","int2",[9,9]),"format":("constantValueInt32","1","format",1),"randomseed":("constantValueInt32","0","int",0)}
    literals=[];tokens={}
    for p in rows:
        name=_leaf(p,"name");_children(p,{"name","relativeTo","paramValue"})
        if _leaf(p,"relativeTo")!="0":raise ValueError("Source parameter must be Absolute")
        value=_one(p.findall("paramValue"),"parameter value")
        if name in expected:
            tag,token,typ,data=expected[name];_children(value,{tag})
            if _leaf(value,tag)!=token:raise ValueError("Source size/format/seed changed")
            literals.append(_typed(owner,"$"+name,typ,data));tokens[name]=token
        elif name=="Disorder":
            _children(value,{"constantValueFloat1"});token=_leaf(value,"constantValueFloat1");_float32(token,0.0)
            literals.append(_typed(owner,name,"float",0.0));tokens[name]=token
        else:
            _children(value,{"constantValueBool"});token=_leaf(value,"constantValueBool")
            if token not in ("0","1"):raise ValueError("Source Invert must be direct Bool")
            literals.append(_typed(owner,name,"bool",token=="1"));tokens[name]=token
    # Omitted exposed parameters have exact official authored defaults, verified by typed view.
    if kind=="noise" and "Disorder" not in names:literals.append(_typed(owner,"Disorder","float",0.0))
    if kind=="invert" and "invert" not in names:literals.append(_typed(owner,"invert","bool",True))
    return literals,tokens

def _image(identifier,category,connectable):
    return dict(id=identifier,category=category,declarations=[dict(class_name="SDTypeTexture",id="SDTypeTexture",modifier=dict(name="Auto",value=0))],
        flags=dict(connectable=connectable,read_only=True,variadic=False,primary=False,function_only=False),function=None)

def _graph(graph,dependencies,packages):
    _children(graph,{"identifier","uid","graphOutputs","compNodes","baseParameters","root"})
    identifier=_leaf(graph,"identifier");gid=_uid(_leaf(graph,"uid"));definitions=[gid]
    outputs=graph.find("graphOutputs");_children(outputs,{"graphoutput"});output=_one(outputs.findall("graphoutput"),"graphoutput")
    _children(output,{"identifier","uid","channels"});out_id=_leaf(output,"identifier");out_uid=_uid(_leaf(output,"uid"));definitions.append(out_uid)
    if _leaf(output,"channels")!="2":raise ValueError("Only grayscale terminal")
    root=graph.find("root");_children(root,{"rootOutputs"});ro=root.find("rootOutputs");_children(ro,{"rootOutput"});rout=ro.find("rootOutput");_children(rout,{"output","format","usertag"})
    if (_leaf(rout,"output"),_leaf(rout,"format"),_leaf(rout,"usertag"))!=(out_uid,"0",""):raise ValueError("Unknown terminal root output")
    _children(graph.find("baseParameters"),{"parameter"},repeated={"parameter"})
    literals,tokens=_params(graph,"baseParameters/parameter","graph","graph")
    container=graph.find("compNodes");_children(container,{"compNode"},repeated={"compNode"});nodes=container.findall("compNode")
    if len(nodes) not in (2,3):raise ValueError("Source topology node budget")
    parsed=[];edges=[];roles={};node_map={};referenced=set()
    for n in nodes:
        uid=_uid(_leaf(n,"uid"));definitions.append(uid)
        if uid in node_map:raise ValueError("Duplicate source node UID")
        node_map[uid]=n;implementation=_one(n.findall("compImplementation"),"node implementation")
        impl=_one(list(implementation),"node implementation type")
        node_keys={"uid","compImplementation"}|({"connections"} if n.find("connections") is not None else set())|({"compOutputs"} if impl.tag=="compInstance" else set())
        _children(n,node_keys);_children(implementation,{impl.tag})
        if impl.tag=="compInstance":
            _children(impl,{"path","parameters","outputBridgings"})
            match=re.fullmatch(r"pkg:///([a-z_]+)\?dependency=([1-9][0-9]{0,19})",_leaf(impl,"path"))
            if match is None or match[2] not in dependencies:raise ValueError("Unknown instance URI/dependency/feedback")
            ref_id,dep=match[1],dependencies[match[2]];role=dep["role"]
            if role not in ("noise","invert") or ref_id!={"noise":"vertical_noise","invert":"invert_grayscale"}[role] or role in roles:raise ValueError("Unknown/duplicate source instance")
            roles[role]=uid;referenced.add(role)
            _children(impl.find("parameters"),{"parameter"},repeated={"parameter"})
            props,raw_tokens=_params(impl,"parameters/parameter",uid,role);literals.extend(props);tokens[uid]=raw_tokens
            co=n.find("compOutputs");_children(co,{"compOutput"});co=co.find("compOutput");_children(co,{"uid","comptype"})
            co_uid=_uid(_leaf(co,"uid"));definitions.append(co_uid)
            if _leaf(co,"comptype")!="2":raise ValueError("Instance must output grayscale")
            bridge=impl.find("outputBridgings");_children(bridge,{"outputBridging"});bridge=bridge.find("outputBridging");_children(bridge,{"uid","identifier"})
            output_name={"noise":"Vertical_Noise","invert":"Invert_Grayscale"}[role]
            if (_leaf(bridge,"uid"),_leaf(bridge,"identifier"))!=(co_uid,output_name):raise ValueError("Output bridge differs")
            parsed.append(dict(id=uid,definition=INSTANCE,reference=dict(package_uid=packages[role]["uid"],package_path=packages[role]["path"],identifier=ref_id),
                inputs=[] if role=="noise" else [_image("Source","Input",True)],output=dict(_image(output_name,"Output",True),uid=co_uid)))
        elif impl.tag=="compOutputBridge":
            _children(impl,{"output"})
            if "terminal" in roles or _leaf(impl,"output")!=out_uid:raise ValueError("Unknown/duplicate terminal")
            roles["terminal"]=uid;parsed.append(dict(id=uid,definition="sbs::compositing::output",reference=None,inputs=[_image("inputNodeOutput","Input",True)],output=dict(_image(out_id,"Output",False),uid=out_uid)))
        else:raise ValueError("Unknown source node definition/function/bitmap")
    if set(roles) not in ({"noise","terminal"},{"noise","invert","terminal"}):raise ValueError("Source topology mismatch")
    indexed={n["id"]:n for n in parsed}
    wanted=[]
    if "invert" in roles:wanted.append([roles["noise"],"Vertical_Noise",roles["invert"],"Source"])
    wanted.append([roles.get("invert",roles["noise"]),"Invert_Grayscale" if "invert" in roles else "Vertical_Noise",roles["terminal"],"inputNodeOutput"])
    for dest,n in node_map.items():
        links=n.find("connections")
        if links is None:continue
        _children(links,{"connection"},repeated={"connection"})
        for link in links:
            _children(link,{"identifier","connRef","connRefOutput"});src=_leaf(link,"connRef")
            if src not in indexed or indexed[src]["reference"] is None or _leaf(link,"connRefOutput")!=indexed[src]["output"]["uid"]:raise ValueError("Unknown image endpoint/output UID")
            edges.append([src,indexed[src]["output"]["id"],dest,_leaf(link,"identifier")])
    if sorted(edges)!=sorted(wanted):raise ValueError("Missing/duplicate/feedback source edge")
    result=dict(identifier=identifier,uid=gid,nodes=parsed,literals=literals,edges=edges,terminal=dict(node_id=roles["terminal"],identifier=out_id,output_id=out_id,category="Output",declarations=_image(out_id,"Output",False)["declarations"]))
    return result,dict(topology="noise_invert_terminal" if "invert" in roles else "noise_terminal",tokens=tokens),referenced,definitions

def _canonical_source_hash(root,dependencies):
    """Comparison only: replace already verified locator scalars, preserve all else."""
    value=copy.deepcopy(root)
    for dep in value.findall("dependencies/dependency"):
        target=dependencies[_leaf(dep,"uid")]
        dep.find("filename").set("v",target["path"])
        dep.find("uid").set("v","canonical-role:"+target["role"]+":"+target["uid"])
    for graph in value.findall("content/graph"):
        for node in graph.findall("compNodes/compNode"):
            instance=node.find("compImplementation/compInstance")
            if instance is None:continue
            path=instance.find("path");match=re.fullmatch(r"pkg:///([^?]+)\?dependency=([0-9]+)",path.get("v"))
            if match is None or match[2] not in dependencies:raise ValueError("Unverified canonical instance binding")
            target=dependencies[match[2]]
            path.set("v","canonical-role:"+target["role"]+":"+target["uid"]+":"+match[1])
    def authored(node):return dict(tag=node.tag,attributes=list(map(list,node.attrib.items())),text=node.text,tail=node.tail,children=[authored(c) for c in node])
    return mask_source.signature(authored(value))


def validate_source(*,selection,packages,stock_references,forbidden_bitmap_paths,source_serialization_base=None):
    """Return a plain authored proof from caller-owned bytes and typed JSON only.

    packages: list of exact {role,path,uid,copy_xml,typed_view} dictionaries.
    Source typed_view={package_uid,graphs}; graphs use the explicit projection in
    _graph. Stock typed_view contains every graph's identifier/class_name. It is
    a projection contract, not evidence that a live SDK producer exists.
    source_serialization_base is lexical only. None preserves legacy source-parent
    behavior/proof bytes; adapters supply their verified owned source-copy parent.
    """
    selected=mask_source.selection(selection,historical=True)
    if type(packages) is not list or not 2<=len(packages)<=3:raise ValueError("Closed package cardinality")
    _fields(stock_references,STOCK_SHA,"official stock references")
    for role,digest in STOCK_SHA.items():
        reference=stock_references[role]
        if type(reference) is not bytes or not 0<len(reference)<=LIMITS["xml_file"] or hashlib.sha256(reference).hexdigest()!=digest:raise ValueError("Official stock SHA mismatch")
    if type(forbidden_bitmap_paths) is not list or len(forbidden_bitmap_paths)>4096:raise ValueError("Invalid forbidden bitmap path list")
    forbidden={mask_source.path(p,resolve=False) for p in forbidden_bitmap_paths}
    rows={};total=0;json_total=0
    for p in packages:
        _fields(p,{"role","path","uid","copy_xml","typed_view"},"registry package")
        if p["role"] not in {"source","noise","invert"} or p["role"] in rows:raise ValueError("Unknown/duplicate role")
        path=mask_source.path(p["path"],resolve=False);uid=mask_source.package_uid(p["uid"])
        if path!=p["path"] or uid!=p["uid"] or path in forbidden:raise ValueError("Non-normalized/forbidden package path or UID")
        if type(p["copy_xml"]) is not bytes:raise ValueError("Expected immutable XML bytes")
        total+=len(p["copy_xml"]);json_total+=len(_json(p["typed_view"]))
        if total>LIMITS["xml_total"] or json_total>LIMITS["json_total"]:raise ValueError("Aggregate registry budget")
        rows[p["role"]]=p
    if not {"source","noise"}<=set(rows) or len({p["path"] for p in rows.values()})!=len(rows) or len({p["uid"] for p in rows.values()})!=len(rows):raise ValueError("Missing/aliased package roles")
    source=rows["source"]
    import os
    base=os.path.dirname(source["path"])
    if source_serialization_base is not None:
        if type(source_serialization_base) is not str or mask_source.path(source_serialization_base,resolve=False)!=source_serialization_base:raise ValueError("Non-normalized source serialization base")
        base=source_serialization_base
    if (source["path"],source["uid"])!=(selected["package_path"],selected["package_uid"]):raise ValueError("Selection package binding mismatch")
    stocks=[_stock(role,rows[role],stock_references[role]) for role in ("noise","invert") if role in rows]
    root=_parse(source["copy_xml"]);_children(root,{"identifier","formatVersion","updaterVersion","fileUID","versionUID","dependencies","content"})
    if mask_source.package_uid(_leaf(root,"fileUID"))!=source["uid"] or _leaf(root,"versionUID")!="0" or _leaf(root,"formatVersion")!="1.1.0.202502" or _leaf(root,"updaterVersion")!="1.1.0.202502":raise ValueError("Source package/header unsupported")
    _leaf(root,"identifier")
    dependency_container=root.find("dependencies");_children(dependency_container,{"dependency"},repeated={"dependency"});deps={};defs=[]
    for dep in dependency_container:
        _children(dep,{"filename","uid","type","fileUID","versionUID"})
        filename=_leaf(dep,"filename");dep_uid=_uid(_leaf(dep,"uid"));defs.append(dep_uid)
        # Resolve strings only. No Path.resolve/stat/open; adapter owns canonical checks.
        import os
        if "://" in filename or "\0" in filename or not filename or filename.startswith(("/","\\")) or re.match(r"^[A-Za-z]:",filename):raise ValueError("Unknown dependency URI")
        target=os.path.normpath(os.path.join(base,filename.replace("/",os.sep)))
        match=[p for p in rows.values() if p["role"]!="source" and p["path"]==target]
        if len(match)!=1 or dep_uid in deps or (_leaf(dep,"type"),_leaf(dep,"fileUID"),_leaf(dep,"versionUID"))!=("package","0","0"):raise ValueError("Unowned/duplicate dependency")
        deps[dep_uid]=match[0]
    content=root.find("content");_children(content,{"graph"},repeated={"graph"});graphs=content.findall("graph")
    if not 1<=len(graphs)<=2 or sum(len(g.findall("compNodes/compNode")) for g in graphs)>5:raise ValueError("Source graph/node budget")
    typed=[];authored=[];closure=set();topologies=set()
    for graph in graphs:
        view,proof,used,ids=_graph(graph,deps,rows)
        if proof["topology"] in topologies or view["identifier"] in {v["identifier"] for v in typed}:raise ValueError("Duplicate graph/topology")
        typed.append(view);authored.append(proof);topologies.add(proof["topology"]);closure|=used;defs+=ids
    if len(defs)!=len(set(defs)) or len(deps)!=len(closure) or {p["role"] for p in deps.values()}!=closure or set(rows)!={"source"}|closure:raise ValueError("Duplicate UID or non-exact full package closure")
    _same(source["typed_view"],dict(package_uid=source["uid"],graphs=typed),"source typed XML/bindings")
    matches=[v for v in typed if v["identifier"]==selected["graph_identifier"] and v["terminal"]["identifier"]==selected["terminal_identifier"]]
    if len(matches)!=1:raise ValueError("Selection terminal missing/ambiguous")
    manifest=dict(schema_version=1,selection=selected,source_xml_sha256=hashlib.sha256(source["copy_xml"]).hexdigest(),graphs=typed,authored=authored,stocks=stocks)
    if source_serialization_base is not None:
        del manifest["source_xml_sha256"]
        manifest.update(source_binding_scheme="canonical_copy_binding_v1",source_canonical_authored_sha256=_canonical_source_hash(root,deps))
    _json(manifest)
    return dict(topology=authored[typed.index(matches[0])]["topology"],selection=selected,bindings=copy.deepcopy(matches[0]),bounds=dict(target=[512,512],format="LUM16",max_intermediate_axis=512,
        basis="fixed official stock bytes plus source/instance Absolute9x9/16bit/seed0/Disorder+0; fixed Noise FX512x256 and other selected image stages512x512",evaluated_output_verified=False),
        authored_manifest=manifest,authored_sha256=mask_source.signature(manifest),native_copy_serializer_supported=False,SDK_adapter_verified=False,feature_active=False)
