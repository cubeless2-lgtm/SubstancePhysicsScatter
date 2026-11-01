"""Exact current-job asset recovery; reads never write or choose an older revision."""
import copy,io,json
from pathlib import Path
from PIL import Image
from substance_physics_scatter.fileio import io_path
import job_assets,pbr_contract as pbr,result_bundle,texture_revision


def load(path,h,work,limit=64*1024*1024):
    path=job_assets.owned(path,work);raw=pbr.read(path,limit)
    if pbr.sha(raw)!=h:raise ValueError('Stored asset sealed SHA differs')
    return raw

def closed(record,current,work):
    if not current:raise ValueError('원본 경로가 없고 검증된 현재 job도 없습니다.')
    bundle=result_bundle.get(current,work);saved=current.get('local_review') or {};ref=saved.get('source_closure');pin=saved.get('asset_renders',{}).get(record['asset_id'])
    if not ref or not pin:raise ValueError('현재 job에 이 자산의 보관 출처가 없습니다.')
    run=Path(current['result_path']).parent;index=pbr.rawjson(load(job_assets.owned(ref['path'],run),ref['sha256'],work,1024*1024));manifest=pbr.rawjson(load(current['request']['review_v1']['manifest_path'],current['request']['review_v1']['manifest_sha256'],work,1024*1024));rows=[r for r in manifest['assets'] if r['asset_id']==record['asset_id']]
    if len(rows)!=1 or manifest['profile']!='material':raise ValueError('Stored canonical material closure required')
    row=rows[0];meta=record['metadata'];files=meta['files']
    if row['physics_obj_sha256']!=files['physics.obj'] or row['corner_data_sha256']!=files['corners.json'] or row['materials']!=meta['material_records'] or pin['glb_sha256']!=files['scene.glb'] or pin['render_revision']!=record.get('render_revision',files['scene.glb']) or pin['material_revision']!=record.get('material_revision'):raise ValueError('최신 자산 revision과 저장 결과가 다릅니다. 이전 재질로 자동 대체하지 않습니다.')
    selected=[r for r in index['files'] if r['asset_id'] in (record['asset_id'],'')];mapping={};digests={}
    for item in selected:
        path=job_assets.owned(item['path'],run)
        if item['source_path'] in mapping and mapping[item['source_path']][1]!=item['sha256']:raise ValueError('Stored source alias ambiguity')
        if item['role']=='original' or item['source_path'] not in mapping:mapping[item['source_path']]=(str(path),item['sha256'])
        digests.setdefault(item['sha256'],str(path))
    aliases=index.get('source_aliases',[])
    if type(aliases) is not list or len(aliases)>256:raise ValueError('Stored source alias budget')
    originals={str(job_assets.owned(r['path'],run)):(r['sha256'],r['bytes']) for r in selected if r['role']=='original'}
    for alias in aliases:
        pbr.exact(alias,('asset_id','source_path','path','sha256','bytes'))
        if alias['asset_id']!=record['asset_id']:continue
        source=str(job_assets.owned(alias['source_path'],work));target=str(job_assets.owned(alias['path'],run))
        if source!=alias['source_path'] or originals.get(target)!=(alias['sha256'],alias['bytes']):raise ValueError('Stored source alias binding')
        if source in mapping and mapping[source][1]!=alias['sha256']:raise ValueError('Stored source alias conflict')
        mapping.setdefault(source,(target,alias['sha256']))
    for source,h in record['source_hashes'].items():
        if source not in mapping or mapping[source][1]!=h:raise ValueError('Stored original source closure differs')
    declared={r['texture_id'] for r in record.get('texture_options',[])}|{r['texture_id'] for r in record.get('material_texture_library',[])}|{r['texture_id'] for r in record.get('manual_textures',[])}|{b['texture_id'] for r in meta['material_records'] for role in texture_revision.ROLES if (b:=r[role+'_texture']) is not None}
    manifest=copy.deepcopy(manifest);manifest['assets']=[row];manifest['textures']=[r for r in manifest['textures'] if r['texture_id'] in declared]
    return dict(bundle=bundle,run=run,index=index,row=row,manifest=manifest,pin=pin,mapping=mapping,digests=digests,job_id=current['job_id'])

def source_raw(record,current,work,path,h,limit=32*1024*1024):
    path=job_assets.owned(path,work)
    if io_path(path).exists():return load(path,h,work,limit),'original'
    view=closed(record,current,work);entry=view['mapping'].get(str(path))
    if entry is None or entry[1]!=h:raise ValueError('원본 파일이 현재 job closure에 포함되지 않았습니다.')
    return load(entry[0],h,work,limit),'job-owned '+view['job_id']

def scene_raw(record,current,work):
    path=Path(record['folder'])/'scene.glb';h=record['metadata']['files']['scene.glb']
    if io_path(job_assets.owned(path,work)).exists():return load(path,h,work),'original'
    view=closed(record,current,work)
    return load(view['pin']['glb_path'],h,work),'job-owned '+view['job_id']

def texture_raw(record,current,work,tid):
    path=job_assets.owned(record['material_manifest'],work)
    if io_path(path).exists():manifest=pbr.rawjson(pbr.read(path,1024*1024));view=None
    else:view=closed(record,current,work);manifest=view['manifest']
    library=texture_revision.library(record,manifest);row=library.get(tid)
    if row is None:raise ValueError('이 자산에 등록되지 않은 texture입니다.')
    path=job_assets.owned(row['path'],work)
    if io_path(path).exists():return load(path,row['content_sha256'],work,8*1024*1024),'original'
    view=view or closed(record,current,work)
    if tid in view['digests']:return load(view['digests'][tid],tid,work,8*1024*1024),'job-owned '+view['job_id']
    options=[r for r in record.get('texture_options',[]) if r['texture_id']==tid]
    if len(options)!=1:raise ValueError('저장 closure에 이 미사용 texture가 없습니다. 다시 추가하세요.')
    source_sha=options[0]['source_sha256'];source=view['digests'].get(source_sha)
    if source is None:raise ValueError('저장 closure에 texture 원본이 없습니다. 다시 추가하세요.')
    original=load(source,source_sha,work,8*1024*1024)
    with Image.open(io.BytesIO(original)) as image:
        if image.size!=(512,512) or image.getexif().get(274,1)!=1:raise ValueError('Stored texture source profile')
        image=image.convert('RGBA');out=io.BytesIO();image.save(out,format='PNG',compress_level=6,icc_profile=None);raw=out.getvalue()
    if pbr.sha(raw)!=tid:raise ValueError('Stored source cannot recover the exact canonical texture bytes')
    texture_revision.rgba(raw)
    return raw,'job-owned exact canonical recovery '+view['job_id']

def needs_recovery(record,work):
    paths=[record['physics'],str(Path(record['folder'])/'scene.glb'),*record.get('source_hashes',{})]
    if 'corners.json' in record['metadata']['files']:paths.append(str(Path(record['folder'])/'corners.json'))
    if record.get('material_manifest'):paths.append(record['material_manifest'])
    if any(not io_path(job_assets.owned(p,work)).exists() for p in paths):return True
    if not record.get('material_manifest'):return False
    manifest=pbr.rawjson(pbr.read(record['material_manifest'],1024*1024))
    return any(not io_path(job_assets.owned(t['path'],work)).exists() for t in manifest['textures'])

def stage(record,current,work,directory,check_space=None):
    if not needs_recovery(record,work):return copy.deepcopy(record)
    view=closed(record,current,work);target=job_assets.owned(directory,work)
    if io_path(target).exists():raise ValueError('New derived asset staging directory required')
    if check_space:check_space(1024*1024)
    io_path(target).mkdir(parents=True,exist_ok=False);result=copy.deepcopy(record);aid=record['asset_id'];folder=view['run']/'inputs/review-assets'/aid
    result['folder']=str(folder);result['physics']=str(folder/'physics.obj');result.setdefault('historical_source_hashes',copy.deepcopy(record['source_hashes']));result['source_hashes']={view['mapping'][p][0]:h for p,h in record['source_hashes'].items()}
    history={**record.get('historical_source_hashes',{}),**record['source_hashes']};result['stored_source_aliases']=[dict(source_path=p,current_path=view['mapping'][p][0],sha256=h) for p,h in history.items() if p in view['mapping'] and view['mapping'][p][1]==h]
    def remap(path,h):
        entry=view['mapping'].get(path)
        return entry[0] if entry and entry[1]==h else path
    for row in result.get('manual_textures',[]):
        for key,hashkey in (('source_path','source_sha256'),('provenance_path','provenance_sha256')):
            if key in row:row[key]=remap(row[key],row[hashkey])
    available=texture_revision.library(record,view['manifest']);recovered=[]
    for tid,row in available.items():
        row=copy.deepcopy(row)
        try:raw,label=texture_raw(record,current,work,tid)
        except (ValueError,FileNotFoundError):
            # Keep the declared unavailable library entry. Selecting it fails
            # explicitly; current material inputs below must all be available.
            recovered.append(row);continue
        if tid in view['digests']:row['path']=view['digests'][tid]
        elif not io_path(job_assets.owned(row['path'],work)).exists():
            path=target/(tid+'.png')
            if check_space:check_space(len(raw)+1024*1024)
            with io_path(path).open('xb') as f:f.write(raw)
            row['path']=str(path)
        recovered.append(row)
    result['material_texture_library']=recovered;by={r['texture_id']:r for r in recovered};used={b['texture_id'] for r in record['metadata']['material_records'] for role in texture_revision.ROLES if (b:=r[role+'_texture']) is not None}
    for tid in used:load(by[tid]['path'],tid,work,8*1024*1024)
    manifest=copy.deepcopy(view['manifest']);row=copy.deepcopy(view['row']);row['corner_data_path']=str(folder/'corners.json');manifest['assets']=[row];manifest['textures']=[by[tid] for tid in sorted(used)];path=target/'material-manifest.json'
    raw=json.dumps(manifest,indent=2,allow_nan=False).encode()
    if len(raw)>1024*1024:raise ValueError('Derived manifest budget')
    with io_path(path).open('xb') as f:f.write(raw)
    result['material_manifest']=str(path);result['source_fallback']='job-owned '+view['job_id'];return result
