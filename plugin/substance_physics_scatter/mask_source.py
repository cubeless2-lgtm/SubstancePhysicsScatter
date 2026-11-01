"""Value-only graph-terminal selection/context; no SDK imports or evaluation."""
from __future__ import annotations
import copy,datetime,hashlib,json,os,re,uuid
from .fileio import logical_path,io_path

SELECTION={"package_path","package_uid","graph_identifier","terminal_identifier"}
CONTEXT=SELECTION|{"graph_url","terminal_node_id","output_id","session_token","loaded_inventory_sha256","authored_sha256"}
CAPTURE={"designer_version","selection","context","pre_authored_sha256","post_authored_sha256","package_modified","disk_file_sha256","captured_at"}
EVALUATOR_TOOLS={"cooker_sha256":"1ebdbe113d5016501e13565b11f3d713877576a2cd563a6bd58e49c644c922fe","renderer_sha256":"9b00406c858b06a8a5e8744f4a5c31b5b16b42d29e425a8ab72944991aee5214","engine_sha256":"2e9d8fca77f45b1a96198074d4b29e0f45dd8eab346c90a3e853769edfb70c08"}
RESELECT="마스크 그래프의 문맥을 확인할 수 없습니다. 소스를 다시 선택하세요."
CROSS_MODE="그래프 출처가 있는 결과는 현재 파일 입력으로 다시 구울 수 없습니다. 저장된 입력으로 다시 굽기를 사용하세요."

def fields(value,wanted,label):
    if not isinstance(value,dict) or set(value)!=wanted:raise ValueError("Invalid "+label+" fields")
    return value
def text(value,label,limit=4096):
    if not isinstance(value,str) or not value or len(value)>limit or "\0" in value:raise ValueError("Invalid "+label)
    return value
def sha(value):
    if not isinstance(value,str) or not re.fullmatch("[0-9a-f]{64}",value):raise ValueError("Invalid SHA256")
    return value
def run_id(value):
    if not isinstance(value,str) or not re.fullmatch("[0-9a-f]{32}",value):raise ValueError("Invalid job/session ID")
    return value
def package_uid(value):
    text(value,"package UID",64)
    try:return str(uuid.UUID(value.strip("{}")))
    except ValueError as error:raise ValueError("Invalid package UID") from error
def path(value,*,resolve=True):
    text(value,"saved package path")
    from pathlib import Path
    if not Path(value).is_absolute():raise ValueError("Saved package path must be absolute")
    return str(logical_path(value)) if resolve else os.path.normpath(os.path.abspath(value))
def timestamp(value):
    text(value,"capture timestamp",128)
    try:parsed=datetime.datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as error:raise ValueError("Invalid capture timestamp") from error
    if parsed.utcoffset() is None:raise ValueError("Capture timestamp needs timezone")
    return value
def encoded(value):return json.dumps(value,sort_keys=True,allow_nan=False,separators=(",",":")).encode("utf8")
def signature(value):return hashlib.sha256(encoded(value)).hexdigest()

def selection(value,*,historical=False):
    fields(value,SELECTION,"selection")
    return dict(package_path=path(value["package_path"],resolve=not historical),package_uid=package_uid(value["package_uid"]),graph_identifier=text(value["graph_identifier"],"graph identifier",512),terminal_identifier=text(value["terminal_identifier"],"terminal identifier",512))

def source(value):
    fields(value,{"schema_version","source_kind","selection"},"mask_source")
    if type(value["schema_version"]) is not int or value["schema_version"]!=1 or value["source_kind"]!="graph_terminal":raise ValueError("Unsupported mask source")
    return dict(schema_version=1,source_kind="graph_terminal",selection=selection(value["selection"]))

def inventory(value):
    if not isinstance(value,list) or len(value)>4096:raise ValueError("Invalid loaded inventory")
    rows=[]
    for item in value:
        fields(item,{"package_path","package_uid"},"inventory item")
        rows.append(dict(package_path=None if item["package_path"] is None else path(item["package_path"]),package_uid=package_uid(item["package_uid"])))
    if len({signature(r) for r in rows})!=len(rows):raise ValueError("Duplicate loaded package identity")
    return sorted(rows,key=lambda r:(r["package_uid"],r["package_path"] or ""))

def context(value,*,historical=False):
    fields(value,CONTEXT,"context");result=selection({k:value[k] for k in SELECTION},historical=historical)
    for key in ("graph_url","terminal_node_id","output_id"):result[key]=text(value[key],key,2048)
    result.update(session_token=run_id(value["session_token"]),loaded_inventory_sha256=sha(value["loaded_inventory_sha256"]),authored_sha256=sha(value["authored_sha256"]))
    return result

def canonical(selected,candidates,loaded):
    selected=selection(selected);loaded=inventory(loaded)
    matches=[r for r in loaded if r["package_uid"]==selected["package_uid"]]
    if len(matches)!=1 or matches[0]["package_path"]!=selected["package_path"] or not io_path(selected["package_path"]).is_file():raise ValueError(RESELECT)
    if not isinstance(candidates,list) or len(candidates)>4096:raise ValueError(RESELECT)
    normalized=[context(c) for c in candidates]
    matches=[c for c in normalized if all(c[k]==v for k,v in selected.items())]
    if len(matches)!=1 or matches[0]["loaded_inventory_sha256"]!=signature(loaded):raise ValueError(RESELECT)
    return copy.deepcopy(matches[0])

def require_selection_context(selected_context,current_context):
    """Selection lifetime excludes normal authored edits before a new operation."""
    before=context(selected_context);after=context(current_context)
    if any(before[k]!=after[k] for k in CONTEXT-{"authored_sha256"}):raise ValueError(RESELECT)

def require_operation_context(before_context,after_context):
    """A single compute/export must keep both lifetime and authored state stable."""
    require_selection_context(before_context,after_context)
    if context(before_context)["authored_sha256"]!=context(after_context)["authored_sha256"]:raise ValueError("Capture authored state changed during operation")

def evaluator(value):
    wanted={"version","backend","cpu_count","engine","cooker_optimization","graph_identifier","terminal_identifier","source_copy_sha256","source_stage_sha256","stocks","archive_sha256","output_png_sha256"}|set(EVALUATOR_TOOLS)
    fields(value,wanted,"capture evaluator")
    if type(value["version"]) is not int or value["version"]!=1 or value["backend"]!="designer_cli_d3d11_cpu1" or type(value["cpu_count"]) is not int or value["cpu_count"]!=1 or value["engine"]!="D3D11" or value["cooker_optimization"]!="default":raise ValueError("Unsupported capture evaluator")
    for k,expected in EVALUATOR_TOOLS.items():
        if sha(value[k])!=expected:raise ValueError("Capture evaluator tool SHA differs")
    for k in ("source_copy_sha256","source_stage_sha256","archive_sha256","output_png_sha256"):sha(value[k])
    for k in ("graph_identifier","terminal_identifier"):text(value[k],k,512)
    stocks=value["stocks"]
    if type(stocks) is not list or [s.get("role") if type(s) is dict else None for s in stocks] not in (["noise"],["noise","invert"]):raise ValueError("Invalid evaluator stock closure")
    for row in stocks:fields(row,{"role","sha256"},"evaluator stock");sha(row["sha256"])
    return copy.deepcopy(value)

def capture(value,*,historical=False):
    fields(value,CAPTURE|({"evaluator"} if isinstance(value,dict) and "evaluator" in value else set()),"capture");result=copy.deepcopy(value)
    result["designer_version"]=text(value["designer_version"],"Designer version",128)
    result["selection"]=selection(value["selection"],historical=historical);result["context"]=context(value["context"],historical=historical)
    if any(result["selection"][k]!=result["context"][k] for k in SELECTION):raise ValueError("Capture selection/context differ")
    if sha(value["pre_authored_sha256"])!=sha(value["post_authored_sha256"]) or value["pre_authored_sha256"]!=result["context"]["authored_sha256"]:raise ValueError("Capture authored state changed")
    if type(value["package_modified"]) is not bool:raise ValueError("Invalid package modified state")
    sha(value["disk_file_sha256"]);timestamp(value["captured_at"])
    if "evaluator" in value:
        result["evaluator"]=evaluator(value["evaluator"])
        if any(result["evaluator"][k]!=result["selection"][k] for k in ("graph_identifier","terminal_identifier")):raise ValueError("Capture evaluator selection differs")
    return result

def graph_family(record):
    """Validated companion summary; previous availability preserves saved history."""
    if record is None:return False
    if not isinstance(record,dict) or type(record.get("capture_available")) is not bool or type(record.get("pile_origin_available")) is not bool:raise ValueError("Invalid validated companion summary")
    previous=record.get("previous_source")
    if previous is not None and (not isinstance(previous,dict) or type(previous.get("companion_available")) is not bool):raise ValueError("Invalid previous companion summary")
    return record["capture_available"] or record["pile_origin_available"] or (previous is not None and previous["companion_available"])

def input_policy(previous_companion,*,rebake,mode):
    if type(rebake) is not bool or mode not in ("current_file","current_graph_terminal","saved_input"):raise ValueError("Invalid host input mode")
    if mode=="saved_input" and not rebake:raise ValueError("Saved input requires rebake")
    if graph_family(previous_companion) and rebake and mode=="current_file":raise ValueError(CROSS_MODE)
