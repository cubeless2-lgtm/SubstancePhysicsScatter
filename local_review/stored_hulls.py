"""Host-only actual Hull inheritance. Native result/sidecar bytes stay untouched."""
import copy,json
from pathlib import Path
from substance_physics_scatter.fileio import io_path
from substance_physics_scatter import compat
import job_assets,pbr_contract as pbr
MAX_FILES=256
MAX_BYTES=128*1024*1024

def encode(value):return json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()
def read(path,h,work,size=None):
    raw=pbr.read(job_assets.owned(path,work),64*1024*1024)
    if pbr.sha(raw)!=h or (size is not None and len(raw)!=size):raise ValueError('Inherited Hull sealed bytes differ')
    return raw

def source_bundle(origin,work,*,canonicalize=False):
    import result_bundle
    value=result_bundle.get(origin,work);root=Path(origin['result_path']).parent
    physical=read(root/'physics_inputs.json',origin['request']['physics_input_hash'],work)
    proof,blobs=compat.source(root.parent.parent,origin,pbr.rawjson(physical));request=pbr.rawjson(blobs.data[proof['source_request_sha256']]);result=pbr.rawjson(blobs.data[proof['source']['record_sha256']])
    if canonicalize:
        # Only this NEW host snapshot uses native raw views. Existing request,
        # result, pointer and source files are never rewritten.
        origin['request']=request;origin['result']=result
    elif origin['request']!=request or origin['result']!=result:raise ValueError('Inherited Hull raw origin snapshot differs')
    value=dict(value);value['watch']=dict(value['watch'])
    for path,h in blobs.paths.items():
        path=job_assets.owned(path,root);raw=read(path,h,work);value['watch'][str(path)]=(h,len(raw))
    return value

def same_geometry(origin,current):
    def rows(c):return sorted((r['asset_id'],r['content_hash'],r['scale']) for r in c['request']['assets'])
    if rows(origin)!=rows(current) or origin['result']['poses']!=current['result']['poses'] or origin['result']['pose_origin']!=current['result']['pose_origin']:raise ValueError('Inherited Hull pose/origin/geometry/scale differs')

def validate(current,work,reference):
    import result_bundle
    pbr.exact(reference,('path','sha256'));run=Path(current['result_path']).parent
    raw=read(job_assets.owned(reference['path'],run),reference['sha256'],work);proof=pbr.rawjson(raw);pbr.exact(proof,('version','origin','origin_sha256','files'))
    if type(proof['version']) is not int or proof['version']!=1 or type(proof['files']) is not list or not 1<=len(proof['files'])<=MAX_FILES:raise ValueError('Inherited Hull proof schema/budget')
    origin=proof['origin']
    if pbr.sha(encode(origin))!=proof['origin_sha256'] or origin['job_id']==current['job_id'] or (origin.get('local_review') or {}).get('inherited_hull'):raise ValueError('Inherited Hull origin snapshot identity')
    root=job_assets.owned(Path(origin['result_path']).parent,work)
    if root.parent!=Path(current['result_path']).parent.parent or root.name!=origin['job_id']:raise ValueError('Inherited Hull origin run owner')
    original=source_bundle(origin,work)
    if original['hulls'] is None or 'hulls' not in original['doc']['artifacts']:raise ValueError('Inherited Hull requires a direct completed actual Hull')
    same_geometry(origin,current);watch={str(Path(reference['path'])):(reference['sha256'],len(raw))};total=0;seen=set()
    for row in proof['files']:
        pbr.exact(row,('source','path','sha256','bytes'));source=str(job_assets.owned(row['source'],work));target=job_assets.owned(row['path'],run)
        if source in seen or original['watch'].get(source)!=(row['sha256'],row['bytes']):raise ValueError('Inherited Hull original watch binding')
        seen.add(source);pbr.whole(row['bytes'],0,64*1024*1024);total+=row['bytes']
        if total>MAX_BYTES:raise ValueError('Inherited Hull aggregate budget')
        read(target,row['sha256'],work,row['bytes']);watch[str(target)]=(row['sha256'],row['bytes'])
    if seen!=set(original['watch']):raise ValueError('Inherited Hull incomplete source bundle')
    watch.update(original['watch'])
    return dict(hulls=copy.deepcopy(original['hulls']),watch=watch,origin_job_id=origin['job_id'],producer=original['doc']['producer'],proof=proof)

def preserve(previous,current,work,check_space):
    import result_bundle
    bundle=result_bundle.get(previous,work)
    if bundle['hulls'] is None:return None,'이전 결과에 검증된 actual Hull 출처가 없습니다.'
    if 'hulls' in bundle['doc']['artifacts']:origin=copy.deepcopy(previous)
    elif bundle.get('inherited'):
        origin=copy.deepcopy(bundle['inherited']['proof']['origin'])
    else:return None,'이전 Hull의 닫힌 origin proof가 없습니다.'
    source=source_bundle(origin,work,canonicalize=True);same_geometry(origin,current);total=sum(n for _,n in source['watch'].values())
    if len(source['watch'])>MAX_FILES or total>MAX_BYTES:return None,'actual Hull 원본 bundle 보관 예산을 초과합니다.'
    check_space(total+1024*1024);run=job_assets.owned(Path(current['result_path']).parent,work);folder=run/'inputs/inherited-hull'
    if io_path(folder).exists():raise ValueError('New inherited Hull directory required')
    io_path(folder).mkdir(parents=True,exist_ok=False);rows=[]
    for i,(path,(h,size)) in enumerate(source['watch'].items()):
        raw=read(path,h,work,size);target=folder/(str(i).zfill(4)+'-'+Path(path).name)
        with io_path(target).open('xb') as f:f.write(raw)
        read(target,h,work,size);rows.append(dict(source=path,path=str(target),sha256=h,bytes=size))
    result_bundle.check_watch(source['watch'],work)
    proof=dict(version=1,origin=origin,origin_sha256=pbr.sha(encode(origin)),files=rows);raw=encode(proof)
    if len(raw)>8*1024*1024:raise ValueError('Inherited Hull proof byte budget')
    path=folder/'proof.json'
    with io_path(path).open('xb') as f:f.write(raw)
    return dict(path=str(path),sha256=pbr.sha(raw)),None
