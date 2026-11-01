"""Closed official Designer D3D11 CPU1 evaluator; no SDK import or fallback.

Only a registry/producer-validated copy closure is accepted by the adapter.
Designer preview textures are not used as this evaluator's result.
"""
from pathlib import Path
import hashlib, os, re, stat, subprocess, threading, time
from xml.parsers import expat
from . import graph_registry, mask_source

TIMEOUT=30
LOG_CAP=2*1024*1024
SBS_CAP=2*1024*1024
ARCHIVE_CAP=16*1024*1024
TOOL_NAMES={"cooker_sha256":"sbscooker.exe","renderer_sha256":"sbsrender.exe","engine_sha256":"plugins/engines/substance_d3d11_blend.dll"}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def safe(path,root=None):
    path=Path(os.path.abspath(os.fspath(path)))
    for part in (path,*path.parents):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Evaluator reparse/symlink path rejected')
    if root is not None and (path==root or not path.is_relative_to(root)):raise ValueError('Evaluator path escapes exact operation')
    return path


def read(path,cap):
    path=safe(path)
    size=path.stat().st_size
    if not path.is_file() or not 0<size<=cap:raise ValueError('Evaluator file size/type bound')
    with path.open('rb') as stream:raw=stream.read(cap+1)
    if len(raw)!=size or path.stat().st_size!=size:raise ValueError('Evaluator file changed during read')
    return raw


def write(path,raw,root):
    path=safe(path,root)
    with path.open('xb') as stream:stream.write(raw)
    if read(path,max(len(raw),1))!=raw:raise ValueError('Evaluator exclusive write differs')
    return path


def map_dependencies(raw,packages,serialization_base):
    """Replace only validated dependency filename value spans; inverse is exact."""
    source=next(p for p in packages if p['role']=='source')
    if source['copy_xml']!=raw:raise ValueError('Source raw copy differs')
    by_path={p['path']:p for p in packages if p['role']!='source'}
    if len(by_path)!=len(packages)-1:raise ValueError('Duplicate stock identity')
    tree=graph_registry._parse(raw);deps=tree.findall('dependencies/dependency')
    if len(deps)!=len(by_path):raise ValueError('Evaluator dependency closure differs')
    stack=[];spans=[];parser=expat.ParserCreate()
    def start(name,attrs):
        if stack==['package','dependencies','dependency'] and name=='filename':
            offset=parser.CurrentByteIndex;end=raw.index(b'>',offset)+1
            matches=list(re.finditer(rb'\bv\s*=\s*([\x22\x27])(.*?)\1',raw[offset:end]))
            if len(matches)!=1 or set(attrs)!={'v'}:raise ValueError('Unsupported dependency filename serialization')
            match=matches[0];spans.append((offset+match.start(2),offset+match.end(2),attrs['v']))
        stack.append(name)
    parser.StartElementHandler=start
    parser.EndElementHandler=lambda name:stack.pop()
    parser.Parse(raw,True)
    if len(spans)!=len(deps):raise ValueError('Dependency byte/tree mapping differs')
    changes=[];used=set()
    for dep,(a,b,token) in zip(deps,spans):
        if graph_registry._leaf(dep,'filename')!=token or not token or '://' in token or '\x00' in token or token.startswith(('/','\\')) or re.match(r'^[A-Za-z]:',token):raise ValueError('Unvalidated dependency locator')
        target=os.path.normpath(os.path.join(serialization_base,token.replace('/',os.sep)))
        stock=by_path.get(target)
        if stock is None or stock['role'] in used:raise ValueError('Unowned/duplicate evaluator dependency')
        role=stock['role']
        if role not in ('noise','invert'):raise ValueError('Unknown evaluator stock role')
        used.add(role);new=('stock/'+role+'.sbs').encode('ascii')
        changes.append(dict(start=a,end=b,old=raw[a:b],new=new,role=role,original_path=target,namespace_uid=graph_registry._leaf(dep,'uid')))
    staged=raw
    for row in reversed(changes):staged=staged[:row['start']]+row['new']+staged[row['end']:]
    inverse=staged;shift=0;positions=[]
    for row in changes:
        at=row['start']+shift;positions.append((at,at+len(row['new']),row['old']))
        shift+=len(row['new'])-(row['end']-row['start'])
    for a,b,old in reversed(positions):inverse=inverse[:a]+old+inverse[b:]
    if inverse!=raw:raise ValueError('Dependency inverse whole-byte proof failed')
    result=graph_registry._parse(staged)
    for original,changed,row in zip(deps,result.findall('dependencies/dependency'),changes):
        changed.find('filename').set('v',graph_registry._leaf(original,'filename'))
    from xml.etree import ElementTree as ET
    if ET.tostring(result)!=ET.tostring(tree):raise ValueError('Non-locator authored tree changed')
    return staged,[dict(role=r['role'],original_path=r['original_path'],namespace_uid=r['namespace_uid'],staged_filename=r['new'].decode('ascii'),original_token_bytes_hex=r['old'].hex()) for r in changes]


def run_child(argv,cwd,log):
    """One own hidden child, bounded streaming log, kill/wait on timeout/error."""
    if os.name!='nt':raise RuntimeError('Official Designer evaluator requires Windows')
    log=safe(log,cwd);started=time.monotonic();overflow=threading.Event();reader_errors=[];size=[0]
    process=None;reader=None
    try:
        with log.open('xb') as stream:
            process=subprocess.Popen([str(x) for x in argv],cwd=str(cwd),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
            def drain():
                try:
                    while True:
                        block=process.stdout.read(65536)
                        if not block:break
                        room=LOG_CAP-size[0]
                        if room:stream.write(block[:room]);size[0]+=min(room,len(block))
                        if len(block)>room:overflow.set();break
                except BaseException as error:reader_errors.append(str(error));overflow.set()
            reader=threading.Thread(target=drain,daemon=True);reader.start()
            while process.poll() is None:
                if overflow.is_set():raise ValueError('Evaluator combined stdout/stderr exceeds2MiB or read failed')
                if time.monotonic()-started>TIMEOUT:raise TimeoutError('Evaluator child timeout30s')
                try:process.wait(timeout=.025)
                except subprocess.TimeoutExpired:pass
            reader.join(2)
            if reader.is_alive():raise RuntimeError('Evaluator log reader did not finish')
            if overflow.is_set() or reader_errors:raise ValueError('Evaluator bounded log failed')
            if process.returncode!=0:raise RuntimeError('Official evaluator failed: exit '+str(process.returncode)+'; log '+str(log))
        return dict(argv=[str(x) for x in argv],exit_code=process.returncode,seconds=time.monotonic()-started,log_path=str(log),log_sha256=digest(read(log,LOG_CAP)) if size[0] else hashlib.sha256(b'').hexdigest(),log_bytes=size[0])
    finally:
        if process is not None:
            try:
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
            finally:
                if reader is not None:reader.join(2)
                if process.stdout is not None and (reader is None or not reader.is_alive()):process.stdout.close()
            if reader is not None and reader.is_alive():raise RuntimeError('Evaluator reader cleanup unacknowledged')


def render(*,packages,serialization_base,selection,installation,work,target,attempt,evidence):
    """Cook once/render once from validated copies; return closed plain metadata."""
    selected=mask_source.selection(selection,historical=True)
    for key in ('graph_identifier','terminal_identifier'):
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,511}',selected[key]):raise ValueError('Unsupported fixed CLI graph/output identifier')
    roles=[p['role'] for p in packages]
    if roles not in (['source','noise'],['source','noise','invert']):raise ValueError('Closed evaluator package set required')
    for p in packages:
        if type(p['copy_xml']) is not bytes or not 0<len(p['copy_xml'])<=SBS_CAP:raise ValueError('Evaluator raw copy budget')
    original=next(p for p in packages if p['role']=='source')['copy_xml']
    source_package=packages[0]
    if source_package['path']!=selected['package_path'] or source_package['uid']!=selected['package_uid']:raise ValueError('Evaluator source selection identity differs')
    staged,mapping=map_dependencies(original,packages,serialization_base)
    installation=safe(installation);tools={k:safe(installation/v) for k,v in TOOL_NAMES.items()}
    def check_tools():
        for k,path in tools.items():
            if digest(read(path,64*1024*1024))!=mask_source.EVALUATOR_TOOLS[k]:raise ValueError('Official evaluator tool SHA differs: '+k)
    check_tools()
    work=safe(work);target=safe(target,work)
    if str(work)!=serialization_base:raise ValueError('Evaluator source serialization base must be exact operation copy directory')
    if target.parent!=work or target.name!='terminal.png' or target.exists():raise ValueError('Exact exclusive capture target required')
    root=safe(work/'renderer',work);root.mkdir(exist_ok=False)
    stage=safe(root/'input',root);stage.mkdir();(stage/'stock').mkdir()
    source=write(stage/'Source.sbs',staged,root);inputs={source:staged}
    for p in packages:
        if p['role']=='source':continue
        name=stage/'stock'/(p['role']+'.sbs');write(name,p['copy_xml'],root);inputs[name]=p['copy_xml']
    cooked=root/'cooked';output=root/'output';cache=root/'cache'
    for path in (cooked,output,cache):path.mkdir()
    evidence('evaluator-staging',dict(source_copy_sha256=digest(original),source_stage_sha256=digest(staged),dependency_mapping=mapping,inverse_whole_bytes_exact=True,stocks=[dict(role=p['role'],sha256=digest(p['copy_xml'])) for p in packages if p['role']!='source']))
    def check_inputs():
        check_tools()
        for path,raw in inputs.items():
            if read(path,SBS_CAP)!=raw:raise ValueError('Owned evaluator input bytes changed')
    cook=[tools['cooker_sha256'],'--inputs',source,'--output-path',cooked,'--output-name','Source','--consistent-header','1']
    check_inputs();evidence('evaluator-cook-command',dict(argv=[str(x) for x in cook],timeout_seconds=TIMEOUT,combined_log_cap=LOG_CAP));attempt('cook');record=run_child(cook,root,root/'cook.log');evidence('evaluator-cook',record);check_inputs()
    archive=cooked/'Source.sbsar';archive_raw=read(archive,ARCHIVE_CAP)
    render_args=[tools['renderer_sha256'],'render','--inputs',archive,'--input-graph','pkg://'+selected['graph_identifier'],'--input-graph-output',selected['terminal_identifier'],'--engine',tools['engine_sha256'],'--cpu-count','1','--memory-budget','256','--cache-dir',cache,'--output-path',output,'--output-name','terminal','--output-format','png']
    evidence('evaluator-render-command',dict(argv=[str(x) for x in render_args],timeout_seconds=TIMEOUT,combined_log_cap=LOG_CAP));attempt('render');record=run_child(render_args,root,root/'render.log');evidence('evaluator-render',record);check_inputs()
    if read(archive,ARCHIVE_CAP)!=archive_raw:raise ValueError('Cooked archive changed during render')
    png=read(output/'terminal.png',SBS_CAP)
    # The adapter's _png also validates exact512² gray16/CRC/decode before handoff.
    if len(png)<33 or png[:8]!=b'\x89PNG\r\n\x1a\n' or png[16:29]!=bytes.fromhex('00000200000002001000000000'):raise ValueError('CPU evaluator output must be512x512 grayscale16 PNG')
    write(target,png,work)
    result=dict(version=1,backend='designer_cli_d3d11_cpu1',cpu_count=1,engine='D3D11',cooker_optimization='default',graph_identifier=selected['graph_identifier'],terminal_identifier=selected['terminal_identifier'],source_copy_sha256=digest(original),source_stage_sha256=digest(staged),stocks=[dict(role=p['role'],sha256=digest(p['copy_xml'])) for p in packages if p['role']!='source'],archive_sha256=digest(archive_raw),output_png_sha256=digest(png),**mask_source.EVALUATOR_TOOLS)
    return mask_source.evaluator(result)
