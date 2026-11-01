"""Independent loopback OBJ inspection service. Existing production modules are read-only."""
from __future__ import annotations
import asyncio,copy,hashlib,json,math,os,re,secrets,shlex,sys,time,uuid,struct
from pathlib import Path
from typing import Literal
from fastapi import FastAPI,Request,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse,HTMLResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,ConfigDict,Field,model_validator

BASE=Path(__file__).resolve().parent;ROOT=BASE.parent;WORK=BASE/'workspace';WORK.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter.core import Jobs,atomic_json
from substance_physics_scatter.fileio import io_path,logical_path
from substance_physics_scatter import motion,live_preview,local_workers
import import_contract,review_contract,canonical_contract,job_assets,result_bundle,pbr_contract,material_revision,result_export,saved_provenance,texture_revision,stored_assets,stored_hulls
import designer_review
MAX_UPLOAD=128*1024*1024;FILE_LIMIT=32*1024*1024;PORT=int(os.environ.get('SCATTER_REVIEW_PORT','8765'))
ORIGIN=f'http://127.0.0.1:{PORT}';TOKEN=secrets.token_hex(32);LOG_LIMIT=4*1024*1024
BLENDER=Path(os.environ.get('SCATTER_BLENDER','C:/Program Files/Blender Foundation/Blender 5.2/blender.exe'))
WORKER=ROOT/'build/Release/scatter_worker.exe'
REVIEW_WORKER=ROOT/'build-review/Release/scatter_worker_review.exe'
BUILD_FINGERPRINT=ROOT/'build-review/review-build-fingerprint.txt'
PBR_WORKER=ROOT/'build-review-live-ready1/Release/scatter_worker_pbr_live.exe'
PBR_FINGERPRINT=ROOT/'build-review-live-ready1/pbr-build-fingerprint.txt'
PERIODIC_WORKER=ROOT/'build-review-live-ready1/Release/scatter_worker_periodic_live.exe'
PERIODIC_FINGERPRINT=ROOT/'build-review-live-ready1/periodic-build-fingerprint.txt'

def periodic_ready():
    return '0.4.0-review.3' in result_bundle.PRODUCERS and PERIODIC_WORKER.is_file() and PERIODIC_FINGERPRINT.is_file()

def owned(path,root=None):
    if root is None:root=WORK
    p=logical_path(path);r=logical_path(root)
    if p==r or not p.is_relative_to(r):raise ValueError('Workspace path boundary')
    # Existing symlink/junction parents must resolve into the same owned workspace.
    return p
def read(path):return json.loads(io_path(path).read_text(encoding='utf-8'))
def write(path,data):
    path=owned(path);temp=path.with_name(path.name+'.tmp')
    with io_path(temp).open('w',encoding='utf-8') as s:json.dump(data,s,ensure_ascii=False,indent=2,allow_nan=False)
    os.replace(io_path(temp),io_path(path))
def sha(path):return hashlib.sha256(io_path(path).read_bytes()).hexdigest()
def identity(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def uid(value):
    if not re.fullmatch('[0-9a-f]{32}',value):raise HTTPException(404,'Unknown ID')
    return value
def safe_name(name):
    if not name or len(name)>120 or Path(name).name!=name or any(c in '/\\:<>"|?*' or ord(c)<32 for c in name) or name.startswith('.') or name.endswith(('.', ' ')) or re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',name,re.I):raise ValueError('Unsafe upload filename')
    return name
def is_busy():return runtime_latched or process is not None or lock.locked() or task is not None and not task.done()
def space_budget(reserve=128*1024*1024):
    total=0
    for p in io_path(WORK).rglob('*'):
        if p.is_file():
            owned(p);total+=p.stat().st_size
            if total+reserve>2*1024*1024*1024:raise ValueError('Review workspace2GiB budget exceeded; preserve/archive it before adding more data')
def bundle_links(folder,obj):
    names={p.name.casefold() for p in folder.iterdir()};total=0
    for path in [obj,*folder.glob('*.mtl')]:
        text=path.read_text(encoding='utf-8-sig');total+=len(text)
        if total>64*1024*1024:raise ValueError('Text mesh budget')
        for line in text.splitlines():
            bits=line.strip().split(None,1)
            if not bits or bits[0].startswith('#'):continue
            key=bits[0].lower()
            if key in ('call','csh'):raise ValueError('OBJ commands are unsupported')
            if key=='mtllib' or key.startswith('map_') or key in ('bump','disp','decal','refl','norm'):
                if len(bits)!=2:raise ValueError('Empty material dependency')
                # First slice supports flat bundles; reject path traversal and unsupported nested locations.
                tokens=shlex.split(bits[1],posix=True);name=tokens[-1] if key!='mtllib' else bits[1].strip().strip('"')
                safe_name(name)
                if name.casefold() not in names:raise ValueError('Missing uploaded material dependency: '+name)
    from PIL import Image
    pixels=0
    for path in folder.iterdir():
        if path.suffix.lower() in ('.png','.jpg','.jpeg'):
            with Image.open(path) as image:
                w,h=image.size;pixels+=w*h
                if w<1 or h<1 or max(w,h)>4096 or pixels>32*1024*1024:raise ValueError('Source texture dimension/aggregate pixel budget')
                image.verify()

class Strict(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class LiveReady(Strict):
    job_id:str=Field(pattern='^[0-9a-f]{32}$');token:str=Field(pattern='^[0-9a-f]{32}$');sequence:int=Field(ge=1,le=1)
class AssetChoice(Strict):
    asset_id:str=Field(pattern='^[0-9a-f]{32}$');scale:float=Field(gt=0,le=100);weight:float=Field(ge=0,le=1000000)
class Sim(Strict):
    count:int=Field(default=40,ge=1,le=5000);width:float=Field(default=4,ge=.1,le=1000);depth:float=Field(default=4,ge=.1,le=1000);seconds:float=Field(default=12,ge=.1,le=120);seed:int=Field(default=1,ge=0,le=4294967295);edges:Literal['open','walls','periodic']='walls'
class Bake(Strict):
    resolution:int=Field(default=512,ge=16,le=2048);height_min:float=Field(default=0,ge=-1000,le=1000);height_max:float=Field(default=2,ge=-1000,le=1000);normal:Literal['DirectX','OpenGL']='OpenGL';samples:int=Field(default=1,ge=1,le=4)
class Run(Strict):
    assets:list[AssetChoice]=Field(min_length=1,max_length=6);simulation:Sim;bake:Bake;mask_id:str|None=None
class RoleSetting(Strict):
    mode:Literal['auto','none','texture']='auto';texture_id:str|None=Field(default=None,pattern='^[0-9a-f]{64}$');channel:Literal['r','g','b','rgb']|None=None;color_space:Literal['sRGB','linear']|None=None;wrap:Literal['repeat','clamp']|None=None;normal_convention:Literal['OpenGL','DirectX']|None=None
class Normalization(Strict):
    units:Literal['m','cm','mm']='m';up_axis:Literal['Z','Y']='Z';forward_axis:Literal['X','-X','Y','-Y','Z','-Z']='Y';import_mode:Literal['auto','override']='auto';parts_mode:Literal['group','split']='group';material_overrides:dict[str,dict[Literal['base_color','roughness','metallic','normal'],RoleSetting]]=Field(default_factory=dict)
    @model_validator(mode='after')
    def keys(self):
        if len(self.material_overrides)>64 or any(not re.fullmatch('0|[1-9][0-9]?',k) or int(k)>63 for k in self.material_overrides):raise ValueError('Material ID namespace')
        for roles in self.material_overrides.values():
            for role,value in roles.items():
                if value.mode=='texture' and value.texture_id is None:raise ValueError('Manual texture ID required')
                if role!='base_color' and value.color_space not in (None,'linear'):raise ValueError('Data role color space must be linear')
        return self

class MaterialFactors(Strict):
    base_color_factor:list[float]|None=Field(default=None,min_length=3,max_length=3)
    roughness_factor:float|None=Field(default=None,ge=0,le=1)
    metallic_factor:float|None=Field(default=None,ge=0,le=1)
class MaterialEdit(Strict):
    factors:dict[str,MaterialFactors]=Field(default_factory=dict,max_length=64)
    bindings:dict[str,dict[Literal['base_color','roughness','metallic','normal'],RoleSetting]]=Field(default_factory=dict,max_length=64)
    @model_validator(mode='after')
    def values(self):
        if not self.factors and not self.bindings:raise ValueError('Choose factor or binding edits')
        for key in self.bindings:
            if not re.fullmatch('0|[1-9][0-9]?',key) or int(key)>63 or not self.bindings[key]:raise ValueError('Binding slot namespace')
        for key,value in self.factors.items():
            if not re.fullmatch('0|[1-9][0-9]?',key) or int(key)>63:raise ValueError('Material ID namespace')
            material_revision.factors(value.model_dump(exclude_none=True))
        return self

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);lock=asyncio.Lock();jobs=Jobs(WORK/'jobs');process=None;task=None;runtime_latched=False
state_path=WORK/'assets.json';assets=read(state_path) if state_path.exists() else {};run_state=dict(status='idle',token=None,events=[],error=None,settings_hash=None)

@app.middleware('http')
async def boundary(request:Request,call_next):
    if request.headers.get('host')!=f'127.0.0.1:{PORT}' or request.client and request.client.host!='127.0.0.1':return JSONResponse({'detail':'Loopback host required'},403)
    origin=request.headers.get('origin')
    if origin is not None and origin!=ORIGIN:return JSONResponse({'detail':'Origin rejected'},403)
    if request.headers.get('sec-fetch-site')=='cross-site':return JSONResponse({'detail':'Cross-site request rejected'},403)
    if request.method not in ('GET','HEAD') and not secrets.compare_digest(request.headers.get('x-review-token',''),TOKEN):return JSONResponse({'detail':'Session token required'},403)
    if request.method in ('POST','PATCH'):
        try:length=int(request.headers.get('content-length','-1'))
        except ValueError:length=-1
        if not 0<=length<=MAX_UPLOAD+1024*1024:return JSONResponse({'detail':'Content length missing or upload too large'},413)
    response=await call_next(request);response.headers['X-Content-Type-Options']='nosniff';response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']=f"default-src 'self'; script-src 'self' 'nonce-{TOKEN}'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self' blob:; worker-src 'none'; object-src 'none'; frame-ancestors 'none'"
    return response

@app.exception_handler(ValueError)
async def value_error(request,error):return JSONResponse({'detail':str(error)},400)

def public_asset(a):
    value={k:v for k,v in a.items() if k not in ('source','folder','physics')}
    value['geometry_reimport_available']=bool(a.get('source')) and io_path(Path(a['source'])).is_file()
    value['source_path_missing']=not value['geometry_reimport_available'] or not io_path(Path(a.get('folder',''))/'scene.glb').is_file()
    return value
def current():
    c=jobs.current
    if not c:return None
    saved=c.get('local_review');bundle=result_bundle.get(c,WORK);doc=bundle['doc'];verified=None
    if bundle['hulls'] is not None:
        producer=bundle['inherited']['producer'] if bundle.get('inherited') else doc['producer']
        verified=dict(implementation=producer['implementation_version'],hull_count=len(bundle['hulls']['hulls']),url=f'/api/hulls/{c["job_id"]}',status=bundle['hull_status'],origin_job_id=bundle['inherited']['origin_job_id'] if bundle.get('inherited') else c['job_id'])
    return dict(job_id=c['job_id'],poses=c['result']['poses'],spawned_count=c['result'].get('spawned_count'),requested_count=c['result'].get('requested_count'),spawn_status=c['result'].get('spawn_status'),stop_reason=c['result'].get('spawn_stop_reason'),execution=c['result']['execution'],settings=saved,review=verified,periodic=bundle.get('periodic'),hull_status=bundle['hull_status'],hull_reason=bundle.get('hull_reason'),maps={k:d['url'] for k,d in bundle['descriptors'].items()},map_descriptors=bundle['descriptors'],height_field=dict(metadata_url=f'/api/height/{c["job_id"]}',data_url=f'/api/height/{c["job_id"]}/data'),motion=motion.links(bundle['motion']['metadata'],f'/api/motion/{c["job_id"]}/metadata',f'/api/motion/{c["job_id"]}/data'),pipeline='N3 periodic PBR' if bundle.get('periodic') else 'N2 material PBR' if 'basecolor' in bundle['descriptors'] else 'N1 geometry/HNC' if doc else 'legacy HNC')
@app.get('/api/state')
async def get_state():return dict(session_token=TOKEN,assets=[public_asset(a) for a in assets.values()],job=run_state,current=current(),operation_busy=is_busy(),capabilities=dict(obj=True,basic_glb_materials=True,hull=PBR_WORKER.is_file(),fbx=True,pbr_bake=PBR_WORKER.is_file(),seamless_periodic=periodic_ready(),selected_asset_limit=6),runtime=dict(worker_exists=PBR_WORKER.is_file(),blender_exists=BLENDER.is_file(),cleanup_latched=runtime_latched))

async def bounded(argv,folder,timeout,cancel=None,events=False):
    global process,runtime_latched
    folder=owned(folder);io_path(folder).mkdir(parents=True,exist_ok=False);records=[];total=0;failure=None
    live_token=cancel['token'] if events and cancel is not None and cancel.get('live') else None
    extra=dict(env=live_preview.environment(live_token)) if live_token else {}
    proc=await asyncio.create_subprocess_exec(*map(str,argv),stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,cwd=str(folder),creationflags=0x08000000 if os.name=='nt' else 0,**extra)
    process=proc
    async def pump(pipe,name):
        nonlocal total,failure
        buffered=b''
        with io_path(folder/(name+'.bin')).open('xb') as out:
            while True:
                chunk=await pipe.read(65536)
                if not chunk:break
                total+=len(chunk)
                if total>LOG_LIMIT:failure='Process log budget exceeded';raise ValueError(failure)
                out.write(chunk)
                if events and name=='stdout':
                    buffered+=chunk
                    if len(buffered)>1024*1024:raise ValueError('Event line too large')
                    while b'\n' in buffered:
                        line,buffered=buffered.split(b'\n',1)
                        if line.strip():
                            event=json.loads(line);records.append(event)
                            if len(records)>10000:raise ValueError('Event count budget')
                            if cancel is not None and cancel['token']==run_state['token']:run_state['events']=records[-100:]
            if buffered.strip():raise ValueError('Incomplete worker event line')
    async def cancelled():
        last_heartbeat=time.monotonic()
        while proc.returncode is None:
            if cancel is not None and cancel['token']==run_state['token'] and run_state['status']=='cancelling':raise InterruptedError('Cancelled')
            if live_token and time.monotonic()-last_heartbeat>=.25:
                live_preview.heartbeat(jobs.directory,live_token,int(proc.pid));last_heartbeat=time.monotonic()
            await asyncio.sleep(.05)
    readers=[asyncio.create_task(pump(proc.stdout,'stdout')),asyncio.create_task(pump(proc.stderr,'stderr'))];watcher=asyncio.create_task(cancelled())
    try:
        if live_token:live_preview.heartbeat(jobs.directory,live_token,int(proc.pid))
        await asyncio.wait_for(asyncio.gather(proc.wait(),*readers,watcher),timeout)
        if proc.returncode!=0:
            detail=next((str(e.get('message'))[:2048] for e in reversed(records) if e.get('event')=='error' and isinstance(e.get('message'),str)),None)
            raise ValueError(detail or 'Process failed; see owned stdout/stderr logs')
        if failure:raise ValueError(failure)
        return records
    finally:
        try:
            if proc.returncode is None:
                proc.terminate()
                try:await asyncio.wait_for(proc.wait(),5)
                except asyncio.TimeoutError:proc.kill();await asyncio.wait_for(proc.wait(),5)
        finally:
            for reader in [*readers,watcher]:
                if not reader.done():reader.cancel()
            await asyncio.gather(*readers,watcher,return_exceptions=True)
            if proc.returncode is None:runtime_latched=True
            else:process=None

async def normalize(folder,source,options):
    if not BLENDER.is_file():raise ValueError('Blender 5.2 executable unavailable')
    originals={str(owned(p)):sha(p) for p in folder.iterdir() if p.is_file()}
    aid=uuid.uuid4().hex;out=owned(folder/aid);out.mkdir();spec=out/'spec.json';suffix=source.suffix.lower();fbx=import_contract.source_info(source) if suffix=='.fbx' else None
    policy=import_contract.unit_policy(fbx,options.import_mode,options.units,options.up_axis,options.forward_axis) if fbx else None
    option_data=options.model_dump(exclude_none=True);dx_ids=[r.get('texture_id') for material in option_data['material_overrides'].values() for role,r in material.items() if role=='normal' and r.get('normal_convention')=='DirectX' and r.get('mode')=='texture']
    if any(r.get('normal_convention')=='DirectX' and r.get('mode')=='auto' for material in option_data['material_overrides'].values() for role,r in material.items() if role=='normal'):dx_ids.append('*')
    registry=await asyncio.to_thread(import_contract.prepare_images,source,out,fbx,dx_ids)
    write(out/'image-registry.json',registry)
    write(spec,dict(source=str(source),output=str(out),format=suffix[1:],**option_data,fbx_policy=policy,image_registry=registry))
    await bounded([BLENDER,'--background','--factory-startup','--disable-autoexec','--python',BASE/'convert_asset.py','--',spec],out/'conversion-log',120)
    if any(sha(path)!=digest for path,digest in originals.items()):raise ValueError('Original upload bytes changed during conversion')
    result=[];index=read(out/'index.json')
    if not 1<=len(index['parts'])<=128:raise ValueError('Imported part count')
    for part in index['parts']:
        metadata_path=owned(out/part,out);part_out=metadata_path.parent;meta=read(metadata_path)
        if not 1<=meta['triangles']<5000 or meta['canonical_coordinate_system']!='RH_Z_UP':raise ValueError('Unexpected importer metadata')
        if set(meta['files'])!={'scene.glb','physics.obj','corners.json'}:raise ValueError('Importer file set differs')
        for name,h in meta['files'].items():
            if name not in ('scene.glb','physics.obj','corners.json') or sha(part_out/name)!=h:raise ValueError('Importer output identity differs')
            if io_path(part_out/name).stat().st_size>(64 if name=='scene.glb' else 8)*1024*1024:raise ValueError('Importer readback budget')
        canonical_contract.validate(io_path(part_out/'physics.obj').read_bytes(),io_path(part_out/'corners.json').read_bytes(),meta['material_records'],meta['material_ready'])
        part_id=aid if len(index['parts'])==1 else uuid.uuid5(uuid.UUID(aid),part).hex
        options_ui=[{k:t[k] for k in ('texture_id','source_name','source_kind','source_sha256','width','height')} for t in registry['textures']]
        record=dict(asset_id=part_id,name=source.name+(' · '+part_out.name if len(index['parts'])>1 else ''),folder=str(part_out),source=str(source),source_hashes=originals,physics=str(part_out/'physics.obj'),url=f'/api/assets/{part_id}/scene.glb',enabled=True,scale=1.,weight=1.,metadata=meta,texture_options=options_ui,import_options=options.model_dump(),render_revision=meta['files']['scene.glb'],material_revision=identity(meta['material_records']))
        if meta['material_ready']:
            textures=[{k:t[k] for k in ('texture_id','path','content_sha256','width','height','channels','bit_depth')} for t in registry['textures']]
            material_manifest=dict(version=1,profile='material',assets=[dict(asset_id=part_id,physics_obj_sha256=meta['files']['physics.obj'],corner_data_path=str(part_out/'corners.json'),corner_data_sha256=meta['files']['corners.json'],materials=meta['material_records'])],textures=textures)
            write(part_out/'material-manifest.json',material_manifest);record['material_manifest']=str(part_out/'material-manifest.json')
        result.append(record)
    return result

@app.post('/api/assets')
async def upload(files:list[UploadFile]=File(...),units:str=Form('m'),up_axis:str=Form('Z'),forward_axis:str=Form('Y'),import_mode:str=Form('auto'),parts_mode:str=Form('group')):
    if is_busy():raise HTTPException(409,'Another operation is active')
    if units not in ('m','cm','mm') or up_axis not in ('Z','Y'):raise ValueError('Unsupported unit/axis')
    async with lock:
        space_budget()
        if sum(a['enabled'] for a in assets.values())>=32:raise ValueError('Active asset library limit32')
        if not 1<=len(files)<=20:raise ValueError('Upload 1 OBJ and up to19 flat sidecars')
        folder=owned(WORK/'imports'/uuid.uuid4().hex);folder.mkdir(parents=True);seen=set();total=0;obj=[]
        for upload in files:
            name=safe_name(upload.filename);suffix=Path(name).suffix.lower()
            if name.casefold() in seen or suffix not in ('.obj','.fbx','.mtl','.png','.jpg','.jpeg'):raise ValueError('Duplicate or unsupported upload file')
            seen.add(name.casefold());path=owned(folder/name)
            with io_path(path).open('xb') as out:
                size=0
                while data:=await upload.read(1024*1024):
                    size+=len(data);total+=len(data)
                    if size>FILE_LIMIT or total>MAX_UPLOAD:raise ValueError('Upload byte budget exceeded')
                    out.write(data)
            if suffix in ('.obj','.fbx'):obj.append(path)
        if len(obj)!=1:raise ValueError('Exactly one OBJ/FBX per upload bundle')
        if obj[0].suffix.lower()=='.obj':bundle_links(folder,obj[0])
        settings=Normalization(units=units,up_axis=up_axis,forward_axis=forward_axis,import_mode=import_mode,parts_mode=parts_mode)
        imported=await normalize(folder,obj[0],settings)
        if sum(a['enabled'] for a in assets.values())+len(imported)>32:raise ValueError('Active asset library limit32')
        for a in imported:assets[a['asset_id']]=a
        write(state_path,assets);return public_asset(imported[0]) if len(imported)==1 else dict(assets=[public_asset(a) for a in imported])

@app.post('/api/assets/{asset_id}/normalize')
async def renormalize(asset_id:str,settings:Normalization):
    uid(asset_id)
    if is_busy():raise HTTPException(409,'Another operation is active')
    if asset_id not in assets:raise HTTPException(404)
    async with lock:
        old=assets[asset_id];source=owned(old['source'])
        if not io_path(source).is_file():raise ValueError('geometry 재가져오기는 원래 source 경로가 필요합니다. 저장 closure는 preview/재질 편집/Saved용으로 재사용하며 DCC import 문맥은 추측하지 않습니다.')
        imported=await normalize(source.parent,source,settings)
        assets[asset_id]['enabled']=False
        for a in imported:a.update(scale=old['scale'],weight=old['weight']);assets[a['asset_id']]=a
        write(state_path,assets);return public_asset(imported[0]) if len(imported)==1 else dict(assets=[public_asset(a) for a in imported])
@app.delete('/api/assets/{asset_id}')
async def remove(asset_id:str):
    uid(asset_id)
    if is_busy():raise HTTPException(409,'Another operation is active')
    if asset_id not in assets:raise HTTPException(404)
    # Keep derivatives referenced by last-good poses; deletion is a library tombstone.
    assets[asset_id]['enabled']=False;write(state_path,assets);return {'removed':asset_id}

@app.post('/api/assets/{asset_id}/material')
async def edit_material(asset_id:str,body:MaterialEdit):
    uid(asset_id)
    if is_busy():raise HTTPException(409,'Another operation is active')
    if asset_id not in assets or not assets[asset_id]['enabled']:raise HTTPException(404)
    async with lock:
        space_budget()
        old=stored_assets.stage(assets[asset_id],jobs.current,WORK,WORK/'derived-assets'/uuid.uuid4().hex,space_budget);destination=owned(WORK/'imports'/uuid.uuid4().hex)
        payload=body.model_dump(exclude_none=True)
        try:revised,changed=material_revision.build_revision(old,WORK,destination,payload['factors'],bindings=payload['bindings'] or None)
        except FileNotFoundError as error:raise ValueError('필요한 texture가 저장 closure에 포함되지 않았습니다. 원본 경로를 복구하거나 texture를 다시 추가하세요.') from error
        if changed:
            staged=dict(assets);staged[asset_id]=revised
            # Adopt in memory only after the atomic catalog write succeeded.
            write(state_path,staged);assets[asset_id]=revised
        return public_asset(revised)

@app.post('/api/assets/{asset_id}/textures')
async def upload_textures(asset_id:str,files:list[UploadFile]=File(...)):
    uid(asset_id)
    if is_busy():raise HTTPException(409,'Another operation is active')
    if asset_id not in assets or not assets[asset_id]['enabled']:raise HTTPException(404)
    async with lock:
        old=stored_assets.stage(assets[asset_id],jobs.current,WORK,WORK/'derived-assets'/uuid.uuid4().hex,space_budget)
        if old['metadata'].get('material_ready') is not True:raise ValueError('Manual textures require a ready canonical UV asset')
        if not 1<=len(files)<=8:raise ValueError('Upload1..8 PNG/JPG textures')
        space_budget(64*1024*1024)
        folder=owned(WORK/'imports'/uuid.uuid4().hex);folder.mkdir(parents=True);sources={};total=0
        for uploaded in files:
            display=safe_name(uploaded.filename);suffix=Path(display).suffix.lower()
            if suffix not in ('.png','.jpg','.jpeg'):raise ValueError('PNG/JPG textures only')
            path=folder/('manual_'+uuid.uuid4().hex+suffix);size=0
            with io_path(path).open('xb') as stream:
                while raw:=await uploaded.read(1024*1024):
                    size+=len(raw);total+=len(raw)
                    if size>8*1024*1024 or total>64*1024*1024:raise ValueError('Manual texture upload budget')
                    stream.write(raw)
            texture_revision.upload_format(pbr_contract.read(path,8*1024*1024))
            sources[path.name]=(path,display,sha(path))
        output=folder/'canonical';output.mkdir()
        registry=await asyncio.to_thread(import_contract.prepare_images,next(iter(sources.values()))[0],output)
        revised=copy.deepcopy(old);manual={row['texture_id']:row for row in old.get('manual_textures',[])}
        options={row['texture_id']:row for row in old.get('texture_options',[])}
        for row in registry['textures']:
            path,display,original_sha=sources[row['source_name']]
            if sha(path)!=original_sha or row['source_sha256']!=original_sha:raise ValueError('Manual texture source changed')
            row.update(source_path=str(path),source_name=display,source_kind='manual_uploaded')
            provenance=folder/('manual_'+row['texture_id']+'.json');write(provenance,{k:row[k] for k in ('texture_id','content_sha256','source_name','source_sha256','width','height','channels','bit_depth')});row.update(provenance_path=str(provenance),provenance_sha256=sha(provenance))
            manual.setdefault(row['texture_id'],row);chosen=manual[row['texture_id']];options[row['texture_id']]={k:chosen[k] for k in ('texture_id','source_name','source_kind','source_sha256','width','height')}
        revised['manual_textures']=list(manual.values());revised['texture_options']=list(options.values())
        manifest=pbr_contract.rawjson(pbr_contract.read(owned(revised['material_manifest']),1024*1024));texture_revision.library(revised,manifest)
        staged=dict(assets);staged[asset_id]=revised;write(state_path,staged);assets[asset_id]=revised
        return public_asset(revised)

@app.get('/api/assets/{asset_id}/textures/{texture_id}')
async def texture_preview(asset_id:str,texture_id:str,channel:str='rgb'):
    uid(asset_id);pbr_contract.hexsha(texture_id)
    if asset_id not in assets:raise HTTPException(404)
    old=assets[asset_id];raw,label=stored_assets.texture_raw(old,jobs.current,WORK,texture_id)
    preview=await asyncio.to_thread(texture_revision.channel_preview,raw,channel)
    return Response(preview,media_type='image/png',headers={'X-Texture-SHA256':texture_id,'X-Channel-Preview':channel,'X-Asset-Source':label})

@app.get('/api/assets/{asset_id}/scene.glb')
async def scene(asset_id:str,revision:str|None=None):
    uid(asset_id)
    if asset_id not in assets:raise HTTPException(404)
    a=assets[asset_id]
    if revision is not None and revision!=a['metadata']['files']['scene.glb']:raise ValueError('Source render revision is historical; reselect the current source')
    raw,label=stored_assets.scene_raw(a,jobs.current,WORK)
    return Response(raw,media_type='model/gltf-binary',headers={'X-Asset-Source':a.get('source_fallback',label)})

@app.get('/api/render/{job_id}/{asset_id}')
async def pinned_render(job_id:str,asset_id:str):
    uid(job_id);uid(asset_id);c=jobs.current
    if not c or c['job_id']!=job_id:raise HTTPException(404)
    pin=c.get('local_review',{}).get('asset_renders',{}).get(asset_id)
    if not pin:raise HTTPException(404,'No pinned render revision')
    result_bundle.get(c,WORK);path=owned(pin['glb_path']);raw=pbr_contract.read(path,64*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=pin['glb_sha256']:raise ValueError('Pinned GLB bytes changed')
    return Response(raw,media_type='model/gltf-binary')

@app.get('/api/hulls/{job_id}')
async def hulls(job_id:str):
    uid(job_id);c=jobs.current
    if c is None or c['job_id']!=job_id or not c.get('local_review',{}).get('review'):raise HTTPException(404,'No verified Hull for this result')
    h=result_bundle.get(c,WORK)['hulls']
    if h is None:raise HTTPException(404,'No verified Hull for this result')
    return h
@app.post('/api/mask')
async def mask(file:UploadFile=File(...)):
    if is_busy():raise HTTPException(409,'Another operation is active')
    async with lock:
        raw=await file.read(FILE_LIMIT+1)
        if len(raw)>FILE_LIMIT:raise ValueError('Mask byte budget')
        from substance_physics_scatter import maskio
        maskio.decode_black(raw);mid=uuid.uuid4().hex;folder=owned(WORK/'masks');folder.mkdir(exist_ok=True);path=owned(folder/(mid+'.png'))
        with io_path(path).open('xb') as s:s.write(raw)
        return dict(mask_id=mid,sha256=sha(path),name=safe_name(file.filename))

def saved_source(body):
    previous=jobs.current
    if previous is None:raise ValueError('Saved 재베이크에는 이전 정상 배치가 필요합니다. 먼저 Simulate 하세요.')
    snapshot=(previous.get('local_review') or {}).get('snapshot')
    if not isinstance(snapshot,dict) or 'mask_id' not in snapshot:raise ValueError('Saved Mask 선택 근거가 없습니다. 먼저 새 배치를 계산하세요.')
    if body.mask_id!=snapshot['mask_id']:raise ValueError('Mask 선택이 변경됐습니다. Saved 재베이크는 저장된 Mask만 사용합니다. 원래 선택으로 복원하거나 Simulate 하세요.')
    return previous

async def execute(body,token,*,rebake=False):
    global run_state
    async with lock:
        before=io_path(WORK/'jobs/current.json').read_bytes() if io_path(WORK/'jobs/current.json').exists() else None
        snapshot=body.model_dump();cancelled=run_state['status']=='cancelling';run_state.update(status='preparing',events=[],error=None);live_registered=False
        try:
            if cancelled:raise InterruptedError('Cancelled before preparation')
            previous=saved_source(body) if rebake else None
            rows=[];records=[];source_current=previous if rebake else jobs.current
            for choice in body.assets:
                a=assets.get(choice.asset_id)
                if not a or not a['enabled']:raise ValueError('Selected asset is unavailable')
                a=stored_assets.stage(a,source_current,WORK,WORK/'derived-assets'/uuid.uuid4().hex,space_budget);records.append(a)
                rows.append(dict(asset_id=choice.asset_id,path=str(owned(a['physics'])),format='obj',scale=choice.scale,weight=choice.weight))
            if len({r['asset_id'] for r in rows})!=len(rows):raise ValueError('Duplicate asset selection')
            mask=None
            if rebake:
                if any(assets[row['asset_id']]['metadata'].get('material_ready') is not True for row in rows):raise ValueError('Saved 재베이크는 N2 재질 입력이 준비된 자산만 지원합니다.')
                request=await asyncio.to_thread(jobs.prepare,rows,body.simulation.model_dump(),body.bake.model_dump(),rebake=True,host_mode='saved_input')
            else:
                if body.mask_id is not None:mask=owned(WORK/'masks'/(uid(body.mask_id)+'.png'))
                request=await asyncio.to_thread(jobs.prepare,rows,body.simulation.model_dump(),body.bake.model_dump(),scatter_mask=mask)
            if run_state['status']=='cancelling':raise InterruptedError('Cancelled during preparation')
            protocol_files=await asyncio.to_thread(saved_provenance.preserve,previous,jobs.active,WORK,space_budget) if rebake else []
            if run_state['status']=='cancelling':raise InterruptedError('Cancelled during Saved provenance preservation')
            job_id=jobs.active['job_id'];run_state.update(status='running',job_id=job_id)
            jobs.active,closure,index=await asyncio.to_thread(job_assets.seal,records,jobs.active,WORK,space_budget,protocol_files);atomic_json(request,jobs.active)
            if run_state['status']=='cancelling' or run_state['token']!=token:raise InterruptedError('Cancelled during input closure')
            pbr_enabled=jobs.active['review_v1']['bake_pbr'];binary=PBR_WORKER;fp=PBR_FINGERPRINT;implementation='0.4.0-review.2'
            if jobs.active['physics_input_format_version']==3:
                if not periodic_ready() or not pbr_enabled:raise ValueError('검증된 N3 periodic/PBR 런타임이 필요합니다.')
                binary=PERIODIC_WORKER;fp=PERIODIC_FINGERPRINT;implementation='0.4.0-review.3'
            before_binary=sha(binary);fingerprint=fp.read_text(encoding='utf8').strip()
            mode='periodic' if implementation=='0.4.0-review.3' else 'pbr'
            if (fingerprint,before_binary)!=result_bundle.LIVE_PRODUCERS[implementation] and (fingerprint,before_binary) not in local_workers.pairs(mode):raise ValueError('Worker build identity differs; register the local build')
            interactive=not rebake
            if interactive:live_preview.begin(jobs.directory,jobs.active,token,binary,'normal',index['renders']);live_registered=True
            events=await bounded([binary,request],owned(WORK/'logs'/token),180 if interactive else 120,dict(token=token,live=interactive),True)
            if run_state['token']!=token or run_state['status']=='cancelling':raise InterruptedError('Cancelled')
            if not events or any(e.get('job_id')!=job_id or e.get('event')=='error' for e in events) or events[-1].get('event')!='completed':raise ValueError('Worker event identity/completion differs')
            candidate=await asyncio.to_thread(jobs.validate,Path(request).parent/'result.json',job_id)
            if rebake and (candidate['result']['execution']!={'physics_executed':False,'body_count':0,'steps':0} or candidate['result']['poses']!=previous['result']['poses'] or candidate['result']['pose_origin']!=previous['result']['pose_origin']):raise ValueError('Saved pose/origin 또는 physics0 보존 검증 실패')
            if run_state['status']=='cancelling':raise InterruptedError('Cancelled during result validation')
            if sha(binary)!=before_binary:raise ValueError('Review binary changed during execution')
            candidate['local_review']=dict(input_mode='saved_input' if rebake else 'current_file',snapshot=snapshot,settings_hash=identity(snapshot),token=token,job_id=job_id,asset_renders=index['renders'],source_closure=closure,pbr_unavailable=index['pbr_unavailable'],review=dict(event=events[-1],build_fingerprint=fingerprint,binary_sha256=before_binary))
            await asyncio.to_thread(result_bundle.get,candidate,WORK)
            if rebake:
                inherited,reason=await asyncio.to_thread(stored_hulls.preserve,previous,candidate,WORK,space_budget)
                if inherited:candidate['local_review']['inherited_hull']=inherited
                if reason:candidate['local_review']['hull_reason']=reason
                await asyncio.to_thread(result_bundle.get,candidate,WORK)
            await asyncio.to_thread(job_assets.verify,index,WORK,True)
            if run_state['status']=='cancelling' or run_state['token']!=token:raise InterruptedError('Cancelled during review validation')
            if sha(binary)!=before_binary:raise ValueError('Review binary changed before promotion')
            jobs.promote(candidate)
            run_state.update(status='completed')
        except (Exception,asyncio.CancelledError) as error:
            jobs.cancel();after=io_path(WORK/'jobs/current.json').read_bytes() if io_path(WORK/'jobs/current.json').exists() else None
            run_state.update(status='cancelled' if isinstance(error,(InterruptedError,asyncio.CancelledError)) or run_state['status']=='cancelling' else 'failed',error=str(error),last_good_preserved=before==after)
        finally:
            if live_registered:
                try:live_preview.finish(jobs.directory,token,run_state['status'])
                except (ValueError,OSError,KeyError,TypeError) as error:run_state['error']='LIVE 종료 상태 기록 실패: '+str(error)
            run_state['finished_at']=time.time()

def queue_run(body,*,rebake=False):
    global task,run_state
    if is_busy():raise HTTPException(409,'One job at a time; unconfirmed process cleanup requires operator inspection')
    if not PBR_WORKER.is_file():raise ValueError('Registered PBR worker unavailable')
    if body.simulation.edges=='periodic':
        if not periodic_ready():raise ValueError('실제 주기 경계 런타임의 검증·연결이 아직 완료되지 않았습니다.')
        if any(not assets.get(a.asset_id,{}).get('metadata',{}).get('material_ready') for a in body.assets):raise ValueError('주기 경계는 UV/PBR 재질 입력이 준비된 자산을 선택하세요.')
    if rebake:
        saved_source(body)
        if not PBR_WORKER.is_file():raise ValueError('Verified N2 worker unavailable')
    space_budget()
    if body.bake.height_max<=body.bake.height_min:raise ValueError('Height maximum must exceed minimum')
    token=uuid.uuid4().hex;run_state=dict(status='queued',token=token,settings_hash=identity(body.model_dump()),events=[],error=None)
    task=asyncio.create_task(execute(body,token,rebake=rebake));return dict(token=token,settings_hash=run_state['settings_hash'])
@app.post('/api/run')
async def run(body:Run):return queue_run(body)
@app.post('/api/rebake')
async def rebake(body:Run):return queue_run(body,rebake=True)
@app.post('/api/cancel/{token}')
async def cancel(token:str):
    uid(token)
    if token!=run_state['token'] or run_state['status'] not in ('queued','preparing','running'):raise HTTPException(409,'Stale or inactive token')
    run_state['status']='cancelling'
    return dict(token=token,status='cancelling')
@app.get('/api/export/{job_id}')
async def export_result(job_id:str):
    uid(job_id)
    if is_busy():raise HTTPException(409,'Wait for the active operation before exporting')
    c=jobs.current
    if not c or c['job_id']!=job_id:raise HTTPException(404,'Only the verified current result can be exported')
    async with lock:
        raw=await asyncio.to_thread(result_export.build,c,WORK)
    return Response(raw,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="scatter-result-{job_id}.zip"','X-Archive-SHA256':hashlib.sha256(raw).hexdigest()})

@app.get('/api/maps/{job_id}/{channel}')
async def maps(job_id:str,channel:str,preview:str|None=None):
    uid(job_id)
    c=jobs.current
    if not c or c['job_id']!=job_id:raise HTTPException(404)
    bundle=result_bundle.get(c,WORK)
    if channel not in bundle['original']:raise HTTPException(404)
    raw=bundle['original'][channel];transform='none'
    if preview is not None:
        if preview!='opengl' or channel not in ('normal','normal_material'):raise ValueError('Only explicit normal OpenGL preview is supported')
        if bundle['descriptors'][channel]['normal_convention']=='DirectX':raw=result_bundle.normal_preview(raw);transform='green-flip-once'
    return Response(raw,media_type='image/png',headers={'X-Source-SHA256':bundle['descriptors'][channel]['byte_sha256'],'X-Preview-Transform':transform})

def selected_bundle(job_id):
    uid(job_id);c=jobs.current
    if not c or c['job_id']!=job_id:raise HTTPException(404)
    return result_bundle.get(c,WORK)

def normal_live_expected():
    return (jobs.active['job_id'],run_state.get('token')) if jobs.active is not None else ('0'*32,'0'*32)
@app.get('/api/live-state')
async def live_state():
    value=await asyncio.to_thread(live_preview.state,jobs.directory,'normal',normal_live_expected(),'/api/live')
    value['session_token']=TOKEN
    if run_state['status'] in ('cancelling','cancelled','failed'):
        value.update(status='cancelled' if run_state['status']=='cancelling' else run_state['status'],frame=None,sequence=None,error=run_state.get('error'))
    return value
@app.post('/api/live-ready')
async def live_ready(body:LiveReady):return await asyncio.to_thread(live_preview.ready,jobs.directory,'normal',body.job_id,body.token,body.sequence,normal_live_expected())
@app.get('/api/live/geometry')
async def live_geometry(job:str,token:str,asset:str):
    raw=await asyncio.to_thread(live_preview.asset,jobs.directory,'normal',job,token,asset,False,normal_live_expected())
    return designer_review.geometry(raw)
@app.get('/api/live/render')
async def live_render(job:str,token:str,asset:str):
    raw=await asyncio.to_thread(live_preview.asset,jobs.directory,'normal',job,token,asset,True,normal_live_expected())
    return Response(raw,media_type='model/gltf-binary',headers={'X-Source-SHA256':motion.digest(raw)})

@app.get('/api/motion/{job_id}/metadata')
async def motion_metadata(job_id:str):
    value=selected_bundle(job_id)['motion']
    return motion.links(value['metadata'],f'/api/motion/{job_id}/metadata',f'/api/motion/{job_id}/data')
@app.get('/api/motion/{job_id}/data')
async def motion_data(job_id:str):
    value=selected_bundle(job_id)['motion']
    if value['raw'] is None or not value['metadata']['available']:raise HTTPException(404,'실제 낙하 기록 없음')
    return Response(value['raw'],media_type='application/json',headers={'X-Source-SHA256':motion.digest(value['raw'])})

@app.get('/api/height/{job_id}')
async def height_metadata(job_id:str):return selected_bundle(job_id)['height_meta']
@app.get('/api/height/{job_id}/data')
async def height_data(job_id:str):
    bundle=selected_bundle(job_id)
    return Response(bundle['height_le'],media_type='application/octet-stream',headers={'X-Decoded-SHA256':bundle['height_meta']['decoded_sha256'],'X-Byte-Order':'little'})
@app.get('/api/pixel/{job_id}/{channel}')
async def pixel(job_id:str,channel:str,x:int=0,y:int=0):
    bundle=selected_bundle(job_id)
    if channel not in bundle['descriptors']:raise HTTPException(404)
    d=bundle['descriptors'][channel]
    if not 0<=x<d['width'] or not 0<=y<d['height']:raise ValueError('Pixel index outside image')
    at=y*d['width']+x;world_height=None
    if channel=='height':
        values=[struct.unpack_from('<H',bundle['height_le'],at*2)[0]];meta=bundle['height_meta'];world_height=meta['height_min']+values[0]/65535*(meta['height_max']-meta['height_min'])
    else:
        im=bundle['decoded'][channel];components=3 if im['mode']=='RGB' else 1;values=list(im['pixels'][at*components:(at+1)*components])
    return dict(job_id=job_id,channel=channel,x=x,y=y,bit_depth=d['bit_depth'],values=values,world_height=world_height,source_sha256=d['byte_sha256'],meaning='original decoded code values before browser color management')

READY_PRESETS={'brick_red':'d5fe57d2a12648b48ced3264f1f9b163','brick_chipped':'fffed2921d6a4235ade6e3325f643dc0','brick_concrete':'fd715ed42e954b9cab2399bf19f0dfd2','rock_granite':'b84f96c4a50f4fe4abbc6662f9e8e023','rock_sandstone':'8fc4338714d34a9987e1c1ee392a97d1','rock_basalt':'dca68648009d425681e1c3be42dc9928'}
PRESET_LIBRARY=Path('D:/Git/Hunyuan3D-2.1/outputs/scatter_review_20261031/asset_library.json')
@app.get('/api/presets/hunyuan-six')
async def hunyuan_six():
    raw=pbr_contract.read(PRESET_LIBRARY,1024*1024)
    if hashlib.sha256(raw).hexdigest()!='ac992e43b6438b0c3f71315ef66ead1f163e50adf312c694f7baa063588f4acd':raise ValueError('Hunyuan source library identity differs')
    library=pbr_contract.rawjson(raw);source={row['asset_id']:row for row in library['assets']}
    if len(source)!=6 or set(source)!=set(READY_PRESETS):raise ValueError('Hunyuan six source closure')
    rows=[]
    for name,aid in READY_PRESETS.items():
        a=assets.get(aid)
        if not a or not a['enabled'] or a['metadata'].get('material_ready') is not True or not a.get('material_manifest'):raise ValueError('Ready Hunyuan preset missing: '+name)
        if not 1<=a['metadata']['triangles']<5000:raise ValueError('Hunyuan triangle profile')
        s=source[name];expected={Path(v['path']).name:v for v in [s['files']['obj'],s['files']['mtl'],*s['textures'].values()]}
        original=a['source_hashes'];originals={};extras={};seen=set()
        for path,h in original.items():
            canonical=str(job_assets.owned(path,WORK))
            if canonical in seen:raise ValueError('Hunyuan duplicate original/source path')
            seen.add(canonical);basename=Path(path).name
            if basename in expected:
                if basename in originals:raise ValueError('Hunyuan duplicate imported original')
                originals[basename]=(path,h)
            else:extras[path]=h
        if set(originals)!=set(expected):raise ValueError('Hunyuan imported originals differ')
        for basename,(path,h) in originals.items():
            info=expected[basename];external=logical_path(info['path'])
            if io_path(external).stat().st_size>32*1024*1024:raise ValueError('Hunyuan original byte budget')
            try:original_raw,_=stored_assets.source_raw(a,jobs.current,WORK,path,h,32*1024*1024)
            except ValueError as error:raise ValueError('Hunyuan source/final_clean SHA differs: '+str(error)) from error
            if not external.is_relative_to(logical_path(PRESET_LIBRARY.parent)) or h!=info['sha256'] or hashlib.sha256(original_raw).hexdigest()!=h or sha(external)!=h:raise ValueError('Hunyuan source/final_clean SHA differs')
        if extras:
            manual=a.get('manual_textures',[])
            if type(manual) is not list or len(manual)>64:raise ValueError('Hunyuan manual texture registration budget')
            registered={};registered_paths=set();pairs=[]
            for texture in manual:
                if type(texture) is not dict or not {'source_path','source_sha256','provenance_path','provenance_sha256'}<=set(texture):raise ValueError('Hunyuan manual source/provenance registration missing')
                pair=[]
                for field,hash_field,limit in (('source_path','source_sha256',8*1024*1024),('provenance_path','provenance_sha256',1024*1024)):
                    path=texture[field];h=pbr_contract.hexsha(texture[hash_field]);canonical=str(job_assets.owned(path,WORK))
                    if path!=canonical or canonical in registered_paths or Path(path).name in expected:raise ValueError('Hunyuan duplicate/ambiguous manual registration')
                    registered_paths.add(canonical);registered[path]=(h,limit);pair.append(path)
                pairs.append(pair)
            if set(extras)-set(registered):raise ValueError('Hunyuan unregistered manual source')
            for pair in pairs:
                used=set(pair)&set(extras)
                if used and used!=set(pair):raise ValueError('Hunyuan incomplete manual source/provenance pair')
            for path,h in extras.items():
                expected_sha,limit=registered[path]
                raw,_=stored_assets.source_raw(a,jobs.current,WORK,path,expected_sha,limit)
                if h!=expected_sha or hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('Hunyuan manual source/provenance SHA or budget differs')
        rows.append(dict(library_id=name,asset_id=aid,name=a['name'],source_sha256=s['files']['obj']['sha256']))
    return dict(assets=rows,source_library_sha256=hashlib.sha256(raw).hexdigest(),kind='actual Hunyuan six canonical records; no synthetic replacements')
@app.get('/designer-review/')
async def designer_review_page():return HTMLResponse((BASE/'web/designer-review.html').read_text(encoding='utf8').replace('__NONCE__',TOKEN))
@app.get('/api/designer-review/state')
async def designer_review_state():return await asyncio.to_thread(designer_review.state,WORK)
@app.get('/api/designer-review/live-state')
async def designer_live_state():
    _,_,_,directory=designer_review.locator()
    value=await asyncio.to_thread(live_preview.state,directory,'graph',None,'/api/designer-review/live');value['session_token']=TOKEN;return value
@app.post('/api/designer-review/live-ready')
async def designer_live_ready(body:LiveReady):
    _,_,_,directory=designer_review.locator()
    return await asyncio.to_thread(live_preview.ready,directory,'graph',body.job_id,body.token,body.sequence)
@app.get('/api/designer-review/live/geometry')
async def designer_live_geometry(job:str,token:str,asset:str):
    _,_,_,directory=designer_review.locator()
    raw=await asyncio.to_thread(live_preview.asset,directory,'graph',job,token,asset)
    return designer_review.geometry(raw)
@app.get('/api/designer-review/geometry')
async def designer_review_geometry(job:str):return Response(designer_review.load(WORK,job)['geometry'],media_type='application/json')
@app.get('/api/designer-review/motion/metadata')
async def designer_motion_metadata(job:str):return designer_review.load(WORK,job)['display']['motion']
@app.get('/api/designer-review/motion/data')
async def designer_motion_data(job:str):
    bundle=designer_review.load(WORK,job);raw=bundle.get('motion')
    if raw is None or not bundle['display']['motion']['available']:raise HTTPException(404,'실제 낙하 기록 없음')
    return Response(raw,media_type='application/json',headers={'X-Source-SHA256':motion.digest(raw)})
@app.get('/api/designer-review/maps/{channel}')
async def designer_review_map(channel:Literal['height','normal','coverage'],job:str,preview:str|None=None):
    if preview not in (None,'opengl'):raise ValueError('Only original OpenGL preview is supported')
    bundle=designer_review.load(WORK,job);raw=bundle['maps'][channel]
    return Response(raw,media_type='image/png',headers={'X-Source-SHA256':hashlib.sha256(raw).hexdigest()})
@app.get('/api/designer-review/height')
async def designer_review_height(job:str):return designer_review.load(WORK,job)['height']
@app.get('/api/designer-review/height/data')
async def designer_review_height_data(job:str):
    bundle=designer_review.load(WORK,job)
    return Response(bundle['height_le'],media_type='application/octet-stream',headers={'X-Decoded-SHA256':bundle['height']['decoded_sha256'],'X-Byte-Order':'little'})
@app.get('/api/designer-review/pixel/{channel}')
async def designer_review_pixel(channel:Literal['height','normal','coverage'],job:str,x:int=0,y:int=0):return designer_review.pixel(designer_review.load(WORK,job),channel,x,y)
@app.get('/')
async def index():return HTMLResponse((BASE/'web/index.html').read_text(encoding='utf-8').replace('__NONCE__',TOKEN))
app.mount('/web',StaticFiles(directory=BASE/'web'),name='web')
app.mount('/vendor/three',StaticFiles(directory=BASE/'node_modules/three'),name='three')
