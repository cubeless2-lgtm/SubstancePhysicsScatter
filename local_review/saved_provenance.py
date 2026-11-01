"""Preserve closed Saved hash references inside the new job; never scan older jobs."""
import re
from pathlib import Path
from substance_physics_scatter import compat
from substance_physics_scatter.fileio import io_path
import job_assets,pbr_contract as pbr,result_bundle

FILE_CAP=16*1024*1024
BYTE_CAP=128*1024*1024
COUNT_CAP=128
DEPTH_CAP=64

def preserve(previous,request,work,check_space):
    new_id=request['job_id'];old_id=previous['job_id']
    if any(type(v) is not str or re.fullmatch('[0-9a-f]{32}',v) is None for v in (new_id,old_id)) or new_id==old_id or request['operation']!='bake':raise ValueError('Saved provenance owner identity')
    base=job_assets.owned(Path(request['output_directory']).parent.parent,work)
    new=job_assets.owned(compat.safe_result(base,new_id).parent,work);old=job_assets.owned(compat.safe_result(base,old_id).parent,work)
    if base!=job_assets.owned(Path(work)/'jobs',work) or Path(request['output_directory'])!=new or Path(previous['result_path'])!=old/'result.json':raise ValueError('Saved provenance exact run owner')
    bundle=result_bundle.get(previous,work);watch={};total=0;values={};plans={};active=set();seen=set()
    def read(path,expected):
        pbr.hexsha(expected);path=job_assets.owned(path,work);raw=pbr.read(path,FILE_CAP)
        if pbr.sha(raw)!=expected:raise ValueError('Saved provenance SHA conflict')
        row=(expected,len(raw));key=str(path)
        if key in watch and watch[key]!=row:raise ValueError('Saved provenance source changed')
        watch[key]=row;return path,raw
    head_path=job_assets.owned(request['pose_source_path'],new)
    if head_path!=new/'pose_source.json':raise ValueError('Saved provenance head path')
    _,head_raw=read(head_path,request['pose_source_hash']);_,physical_raw=read(new/'physics_inputs.json',request['physics_input_hash'])
    proof,blobs=compat.source(base,previous,pbr.rawjson(physical_raw))
    head=pbr.rawjson(head_raw)
    if head!=proof:raise ValueError('Saved provenance head differs from verified previous source')
    # Only fixed files actually read by the accepted protocol validator can be
    # candidates. No hash search, glob, or reference to an older run is used.
    fixed={}
    for name,h in blobs.paths.items():
        path=job_assets.owned(name,old)
        if path.parent==old and path.name in ('request.json','result.json','pose_source.json','physics_inputs.json'):fixed[h]=path
    def load(h):
        nonlocal total
        pbr.hexsha(h)
        if h in values:return values[h]
        if len(values)>=COUNT_CAP:raise ValueError('Saved provenance file count budget')
        target=new/'physics_inputs.json' if h==request['physics_input_hash'] else new/'provenance'/(h+'.json')
        target=job_assets.owned(target,new);source=target
        if io_path(target).exists():source,raw=read(target,h)
        else:
            candidate=job_assets.owned(old/'provenance'/(h+'.json'),old)
            if io_path(candidate).exists():source,raw=read(candidate,h)
            elif h in fixed:source,raw=read(fixed[h],h)
            else:raise ValueError('Saved 이전 job에도 필요한 전이 출처 raw가 없습니다. 과거 폴더 자동 탐색 없이 중단합니다.')
        if total+len(raw)>BYTE_CAP:raise ValueError('Saved provenance aggregate budget')
        total+=len(raw);values[h]=raw;plans[str(target)]=dict(role='protocol_provenance',asset_id='',source_path=str(source),path=str(target),sha256=h,bytes=len(raw))
        return raw
    def walk(doc,depth=0):
        if depth>DEPTH_CAP:raise ValueError('Saved provenance depth budget')
        for field in ('source_input_sha256','source_request_sha256'):
            if field in doc:load(doc[field])
        if 'source_pose_source_sha256' in doc:
            h=doc['source_pose_source_sha256'];raw=load(h)
            if h in active:raise ValueError('Saved provenance cycle')
            if h not in seen:
                active.add(h);walk(pbr.rawjson(raw),depth+1);active.remove(h);seen.add(h)
        for field in ('origin','source'):
            if field in doc:load(doc[field]['record_sha256'])
        for step in doc.get('legacy_chain',[]):
            for field in ('request_sha256','result_sha256','key_material_sha256'):load(step[field])
        if 'source' in doc and 'source_request_sha256' in doc:
            q=pbr.rawjson(values[doc['source_request_sha256']]);r=pbr.rawjson(values[doc['source']['record_sha256']])
            if q['job_id']!=r['job_id'] or r['job_id']!=doc['source']['job_id'] or q['operation']!=r['operation']:raise ValueError('Saved provenance paired request/result owner')
            if r['operation']=='bake' and (type(doc.get('source_pose_source_sha256')) is not str or q.get('pose_source_hash')!=doc['source_pose_source_sha256']):raise ValueError('Saved provenance paired request/bundle hash')
    walk(head)
    head_row=dict(role='protocol_provenance',asset_id='',source_path=str(head_path),path=str(head_path),sha256=request['pose_source_hash'],bytes=len(head_raw))
    if len(plans)+1>COUNT_CAP or total+len(head_raw)>BYTE_CAP:raise ValueError('Saved provenance head/aggregate budget')
    check_space(total+len(head_raw))
    def unchanged():
        result_bundle.check_watch(bundle['watch'],work)
        for path,(h,size) in watch.items():
            _,raw=read(path,h)
            if len(raw)!=size:raise ValueError('Saved provenance source length changed')
    unchanged()
    for row in plans.values():
        target=Path(row['path']);raw=values[row['sha256']]
        if not io_path(target).exists():
            io_path(target.parent).mkdir(exist_ok=True)
            target=job_assets.owned(target,new)
            with io_path(target).open('xb') as stream:stream.write(raw)
        _,written=read(target,row['sha256'])
        if len(written)!=row['bytes']:raise ValueError('Saved provenance copied length')
    unchanged()
    return [head_row,*plans.values()]
