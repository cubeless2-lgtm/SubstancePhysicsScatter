"""File-only migration fixture. Never load its staging source into Designer."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
from xml.etree import ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"plugin"))
from substance_physics_scatter.fileio import io_path,logical_path

def walk(directory,pattern="*"):
    for path in io_path(directory).rglob(pattern):yield Path(directory)/path.relative_to(io_path(directory))

def owned(path, work):
    path,work=logical_path(path),logical_path(work)
    if path==work or not path.is_relative_to(work):
        raise ValueError("Fixture path escapes unique WORK: "+str(path))
    return path

def strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,dict):
        for child in value.values():yield from strings(child)
    elif isinstance(value,list):
        for child in value:yield from strings(child)

def within_text(value, prefix):
    value=value.replace("\\","/").casefold().rstrip("/")
    prefix=str(prefix).replace("\\","/").casefold().rstrip("/")
    return value==prefix or value.startswith(prefix+"/")

def rebase(value, old_work, staging):
    if isinstance(value,dict):return {key:rebase(child,old_work,staging) for key,child in value.items()}
    if isinstance(value,list):return [rebase(child,old_work,staging) for child in value]
    if isinstance(value,str) and Path(value).is_absolute():
        original=logical_path(value)
        if original.is_relative_to(old_work):return str(staging/original.relative_to(old_work))
    return value

def fingerprint(directory):
    return {str(p.relative_to(directory)):hashlib.sha256(io_path(p).read_bytes()).hexdigest()
            for p in walk(directory) if io_path(p).is_file()}

def proof_fingerprint(roots, work):
    paths=[]
    for root in roots:paths.extend([root] if io_path(root).is_file() else (p for p in walk(root) if io_path(p).is_file()))
    return {str(path.relative_to(work)):hashlib.sha256(io_path(path).read_bytes()).hexdigest() for path in paths}

def xml_payloads(tree):
    for element in tree.iter():
        value=element.get("v","")
        if value.startswith(("{","[")):
            try:decoded=json.loads(value)
            except json.JSONDecodeError:continue
            if isinstance(decoded,(dict,list)):yield element,decoded

def inspect(directory, package_name, old_roots, destination):
    tree=ET.parse(io_path(directory/package_name))
    linked=[element.get("v") for element in tree.iter("filepath")]
    if not linked or any(Path(path).is_absolute() for path in linked):
        raise ValueError("Expected genuine relative Linked filepaths")
    values=[]
    payload_elements=set()
    for element,decoded in xml_payloads(tree):
        payload_elements.add(id(element));values.extend(strings(decoded))
    for element in tree.iter():
        if id(element) not in payload_elements:values.extend(element.attrib.values())
    # current.json and SBS metadata are mutable runtime pointers. Raw protocol records are immutable.
    for path in walk(directory,"current.json"):values.extend(strings(json.loads(io_path(path).read_text(encoding="utf-8"))))
    old_fallback=[value for value in values if any(within_text(value,root) for root in old_roots)]
    injected=[value for value in values if within_text(value,destination)]
    absolute=[logical_path(value) for value in values if Path(value).is_absolute()]
    if old_fallback or injected:raise ValueError("oldmain fallback or destination path injected into source fixture")
    if any(not path.is_relative_to(directory) or not io_path(path).exists() for path in absolute):
        raise ValueError("Staging owned absolute path is missing or outside source")
    linked_paths=[owned(directory/path,directory) for path in linked]
    if any(not io_path(path).is_file() for path in linked_paths):raise ValueError("Staging Linked file is missing")
    return dict(relative_linked=linked,owned_absolute_paths=sorted({str(p) for p in absolute}),
                oldmain_fallback_count=len(old_fallback),destination_injected_count=len(injected),
                source_prefix_count=len(absolute),all_owned_exist_before_park=True)

def prepare(main_package, original_assets, work, *, namespace="migration"):
    """Copy main proof -> never-loaded staging -> byte-identical moved, then park staging only."""
    work=logical_path(work);main_package=owned(main_package,work);original_assets=owned(original_assets,work)
    result_root=owned(main_package.with_name(main_package.stem+"_PhysicsScatter"),work)
    roots=(main_package,result_root,original_assets)
    for root in roots:
        for path in ([root] if io_path(root).is_file() else walk(root)):
            owned(path,work)
            if io_path(path).is_symlink():raise ValueError("Fixture source must not contain symlinks")
    main_before=proof_fingerprint(roots,work)
    if namespace not in ("migration","legacy_migration"):raise ValueError("Invalid migration owner namespace")
    source=owned(work/namespace/"source",work);moved=owned(work/namespace/"moved",work);parked=owned(work/namespace/"parked_source",work)
    if any(io_path(path).exists() for path in (source,moved,parked)):raise ValueError("Migration fixture already exists")
    io_path(source).mkdir(parents=True)
    shutil.copyfile(io_path(main_package),io_path(source/main_package.name))
    shutil.copytree(io_path(result_root),io_path(source/result_root.name))
    shutil.copytree(io_path(original_assets),io_path(source/original_assets.name))
    package=source/main_package.name;tree=ET.parse(io_path(package));old_home=main_package.parent
    immutable_before={str(path.relative_to(source)):hashlib.sha256(io_path(path).read_bytes()).hexdigest() for path in walk(source,"*.json") if path.name!="current.json"}
    relative_before=[element.get("v") for element in tree.iter("filepath")]
    for element,decoded in xml_payloads(tree):element.set("v",json.dumps(rebase(decoded,old_home,source),ensure_ascii=False))
    tree.write(io_path(package),encoding="utf-8",xml_declaration=True)
    for path in walk(source,"current.json"):
        decoded=json.loads(io_path(path).read_text(encoding="utf-8"))
        io_path(path).write_text(json.dumps(rebase(decoded,old_home,source),indent=2,ensure_ascii=False),encoding="utf-8")
    if any(hashlib.sha256(io_path(source/path).read_bytes()).hexdigest()!=digest for path,digest in immutable_before.items()):raise ValueError("Immutable protocol JSON was rewritten")
    audit=inspect(source,main_package.name,roots,moved)
    if relative_before!=audit["relative_linked"]:raise ValueError("Relative Linked paths were modified")
    before=fingerprint(source);shutil.copytree(io_path(source),io_path(moved))
    if fingerprint(moved)!=before:raise ValueError("staging to moved byte identity failed")
    source=owned(source,work);parked=owned(parked,work)
    io_path(source).rename(io_path(parked))
    absent=not io_path(source).exists() and all(not io_path(path).exists() for path in audit["owned_absolute_paths"])
    linked_exist=all(io_path(owned(moved/path,work)).is_file() for path in audit["relative_linked"])
    if not absent or not linked_exist:raise ValueError("Source absence/destination Linked existence proof failed")
    main_after=proof_fingerprint(roots,work)
    if main_before!=main_after:raise ValueError("Main proof files changed during fixture preparation")
    audit.update(source=str(source),parked_source=str(parked),moved=str(moved),
                 staging_never_loaded=True,relative_linked_unchanged=True,copy_byte_identical=True,
                 copied_files_sha256=before,source_prefix_absent_after_park=absent,
                 destination_relative_linked_files_exist=linked_exist,main_proof_untouched=True,
                 main_proof_sha256_before=main_before,main_proof_sha256_after=main_after)
    audit.update(immutable_json_sha256=immutable_before,immutable_json_rewritten_count=0,oldmain_audit_scope="mutable current.json and SBS metadata; immutable raw records intentionally retain original bytes")
    return moved/main_package.name,audit
