"""Job-owned provisional frames, never a completed/promotion proof. No SDK imports."""
from pathlib import Path
import copy,ctypes,json,math,os,struct,time,uuid
from . import motion,mask_source,local_workers
from .fileio import io_path

PRODUCERS={
 'aa5238c8238e94ca115220584aa4f1c732d2b9762bd383f1b40b2f0eb303f136':'2fd5fb09ca4ee64f5e825db9696ffac00477dd059f708c7fca74ba39ba45c3ae',
 '93793019f5549db80e8235274d4a3f874110282540af980b6a9afacb746a3fd8':'8fa5a777bd41050729037c368a79126afadfd7c234ac7ae633cbfb820581d098',
 '21894422682a0455762dcd0bdd2ca0d4c3432a1d7e904d15e08720c8a8d72527':'d0703a1aa38c23300c7dd3cac77d731413855dae35a0ca5e5515dbda5eb2daa3'}
PRODUCERS.update({
 '910ac079f0c003a38a80d6ad5792b26262a9df3293e62de2b46a9eee54f118a1':'2c7bc9a8f790f407f0a962b5729a47b09df8ffeaa326e68295558ec337204cbf',
 '1b613147a7c08a2b91202cd3bab84a5c4eb5dd6bb20e8ab9cec98cb272f358d2':'e2fe4cbabd63f46c10f0b728d48e2fa9a07cee4686d0978217d202aa8abd5a96',
 'c70ff545e18c153679a2d45e3a6848f6a59effd2f4a001c84682be8d61a19a79':'6b48cb93dd09e2f1035ae7919cd9815dc91d8e164d5f6003be420041cef74320'})
_cache={}

def read(path,limit):
    if os.name=='nt':
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];api.CreateFileW.restype=wintypes.HANDLE
        api.GetFileSizeEx.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_longlong)];api.GetFileSizeEx.restype=wintypes.BOOL
        api.ReadFile.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p];api.ReadFile.restype=wintypes.BOOL
        api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle.restype=wintypes.BOOL
        handle=api.CreateFileW(str(io_path(path)),0x80000000,7,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            size=ctypes.c_longlong()
            if not api.GetFileSizeEx(handle,ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
            if not 0<size.value<=limit:raise ValueError('Live file size bound')
            result=bytearray()
            while len(result)<size.value:
                count=min(65536,size.value-len(result));buffer=ctypes.create_string_buffer(count);received=wintypes.DWORD()
                if not api.ReadFile(handle,buffer,count,ctypes.byref(received),None):raise ctypes.WinError(ctypes.get_last_error())
                if not received.value:raise ValueError('Live immutable handle truncated during read')
                result.extend(buffer.raw[:received.value])
            return bytes(result)
        finally:api.CloseHandle(handle)
    p=io_path(path);size=p.stat().st_size
    if not 0<size<=limit:raise ValueError('Live file size bound')
    with p.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)!=size:raise ValueError('Live file changed during read')
    return raw
def atomic(path,value,root):
    p=motion.owned(path,root);temp=motion.owned(p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp'),root)
    raw=mask_source.encoded(value)
    if len(raw)>65536:raise ValueError('Live registration exceeds64KiB')
    with io_path(temp).open('xb') as stream:stream.write(raw)
    try:
        for attempt in range(6):
            try:io_path(temp).replace(io_path(p));return
            except PermissionError as error:
                if getattr(error,'winerror',None) not in (32,33) or attempt==5:raise
                time.sleep(.002)
    finally:
        if io_path(temp).exists():io_path(temp).unlink()
def descriptor_path(jobs):return motion.owned(Path(jobs)/'live-active-v1.json',jobs)
def begin(jobs,request,token,executable,kind,renders=None):
    if kind not in ('normal','graph'):raise ValueError('Closed live source kind')
    mask_source.run_id(token);job=mask_source.run_id(request['job_id']);root=Path(os.path.abspath(jobs));run=motion.owned(root/'runs'/job,root)
    if request['operation'] not in ('simulate','simulate_bake'):return None
    if Path(os.path.abspath(request['output_directory']))!=run:raise ValueError('Live exact output owner')
    exe=motion.owned(executable,Path(executable).anchor);exe_sha=motion.digest(read(exe,64*1024*1024))
    fp=next((k for k,v in PRODUCERS.items() if v==exe_sha),None)
    if fp is None:fp=next((f for mode in local_workers.MODES for f,h in local_workers.pairs(mode) if h==exe_sha),None)
    if fp is None:raise ValueError('Unapproved interactive live binary')
    request_raw=read(motion.owned(run/'request.json',root),2*1024*1024)
    if mask_source.encoded(motion.decode(request_raw))!=mask_source.encoded(request):raise ValueError('Live request snapshot differs')
    physical=motion.owned(run/'physics_inputs.json',root)
    if motion.digest(read(physical,16*1024*1024))!=request['physics_input_hash']:raise ValueError('Live physical raw SHA differs')
    if io_path(run/'live-frame-v1.json').exists():raise ValueError('Fresh live job must not have an earlier frame')
    if io_path(run/'result.json').exists():raise ValueError('Completed job cannot be registered as live')
    assets=[];seen=set()
    for a in request['assets']:
        aid=mask_source.run_id(a['asset_id']);h=mask_source.sha(a['content_hash'])
        if aid in seen or len(seen)>=6:raise ValueError('Live duplicate/asset budget')
        seen.add(aid);expected=(run/'inputs/review-assets'/aid/'physics.obj') if kind=='normal' else root/'assets'/(h+'.obj')
        if Path(os.path.abspath(a['path']))!=expected:raise ValueError('Live geometry exact cache/closure path')
        raw=read(motion.owned(expected,root),32*1024*1024)
        if motion.digest(raw)!=h:raise ValueError('Live sealed geometry differs')
        render=None;pin=(renders or {}).get(aid)
        if pin:
            glb=motion.owned(pin['glb_path'],run)
            if glb!=run/'inputs/review-assets'/aid/'scene.glb':raise ValueError('Live exact GLB closure path')
            g=read(glb,64*1024*1024)
            if motion.digest(g)!=pin['glb_sha256']:raise ValueError('Live sealed render revision differs')
            render=dict(path=str(glb),sha256=pin['glb_sha256'])
        assets.append(dict(asset_id=aid,scale=a['scale'],content_hash=h,geometry_path=str(expected),render=render))
    value=dict(schema_version=1,status='starting',kind=kind,job_id=job,token=token,nonce=token,pid=0,
               producer=dict(implementation_version='0.4.0-live.1',build_fingerprint=fp,binary_sha256=exe_sha),
               physics_input_hash=request['physics_input_hash'],request_sha256=motion.digest(request_raw),assets=assets,
               region={k:request['simulation'][k] for k in ('width','depth','edges')},solver_hz=60 if request['physics_input_format_version']==3 else 120)
    atomic(descriptor_path(root),value,root);return value
def heartbeat(jobs,token,pid):
    value=motion.decode(read(descriptor_path(jobs),65536))
    if value['token']!=token or value['status'] not in ('starting','running'):return
    if type(pid) is not int or pid<=0:raise ValueError('Live actual process PID unavailable')
    if value['pid'] not in (0,pid):raise ValueError('Live process ownership changed')
    value.update(pid=pid,status='running');atomic(descriptor_path(jobs),value,jobs)
def finish(jobs,token,status):
    path=descriptor_path(jobs)
    if not io_path(path).exists():return
    value=motion.decode(read(path,65536))
    if value['token']!=token:return
    if status not in ('completed','failed','cancelled'):raise ValueError('Live terminal status')
    value.update(status=status,pid=0);atomic(path,value,jobs)
def environment(token):
    value=os.environ.copy();value.update(SCATTER_LIVE_PREVIEW='1',SCATTER_LIVE_NONCE=mask_source.run_id(token),SCATTER_LIVE_WAIT_READY='1');return value

def registration(jobs,kind,expected=None):
    path=descriptor_path(jobs)
    if not io_path(path).exists():return None
    raw=read(path,65536);d=motion.decode(raw)
    motion.exact(d,('schema_version','status','kind','job_id','token','nonce','pid','producer','physics_input_hash','request_sha256','assets','region','solver_hz'))
    if type(d['schema_version']) is not int or d['schema_version']!=1 or d['kind']!=kind or d['status'] not in ('starting','running','completed','failed','cancelled'):raise ValueError('Live registration contract')
    mask_source.run_id(d['job_id']);mask_source.run_id(d['token'])
    if d['nonce']!=d['token']:raise ValueError('Live token nonce binding')
    motion.integer(d['pid'],0,0xffffffff)
    if type(d['solver_hz']) is not int or d['solver_hz'] not in (60,120):raise ValueError('Live fixed solver Hz')
    mask_source.sha(d['physics_input_hash']);mask_source.sha(d['request_sha256'])
    p=d['producer'];motion.exact(p,('implementation_version','build_fingerprint','binary_sha256'))
    if p['implementation_version']!='0.4.0-live.1':raise ValueError('Live registration producer')
    pair=(p['build_fingerprint'],p['binary_sha256'])
    if PRODUCERS.get(pair[0])!=pair[1] and not any(pair in local_workers.pairs(mode) for mode in local_workers.MODES):raise ValueError('Live registration producer')
    root=Path(os.path.abspath(jobs));run=motion.owned(root/'runs'/d['job_id'],root)
    raw=read(motion.owned(run/'request.json',root),2*1024*1024)
    if motion.digest(raw)!=d['request_sha256']:raise ValueError('Live original request changed')
    request=motion.decode(raw)
    if request['job_id']!=d['job_id'] or request['physics_input_hash']!=d['physics_input_hash'] or request['operation'] not in ('simulate','simulate_bake') or d['region']!={k:request['simulation'][k] for k in ('width','depth','edges')}:raise ValueError('Live request/region/physics binding')
    if motion.digest(read(motion.owned(run/'physics_inputs.json',root),16*1024*1024))!=d['physics_input_hash']:raise ValueError('Live immutable physics input changed')
    if type(d['assets']) is not list or not 1<=len(d['assets'])<=6:raise ValueError('Live assets bound')
    expected_assets={a['asset_id']:a for a in request['assets']}
    if len(expected_assets)!=len(d['assets']) or {a['asset_id'] for a in d['assets']}!=set(expected_assets):raise ValueError('Live asset identity count')
    for a in d['assets']:
        motion.exact(a,('asset_id','scale','content_hash','geometry_path','render'));mask_source.run_id(a['asset_id']);mask_source.sha(a['content_hash'])
        original=expected_assets.get(a['asset_id'])
        if original is None or any(a[k]!=original[k] for k in ('scale','content_hash')) or a['geometry_path']!=original['path']:raise ValueError('Live source asset binding')
        if a['render'] is not None:motion.exact(a['render'],('path','sha256'));mask_source.sha(a['render']['sha256'])
    if d['status'] in ('starting','running'):
        if expected is not None and (d['job_id'],d['token'])!=expected:raise ValueError('Live registration is not the active owned job/token')
        if time.time()-io_path(path).stat().st_mtime>3:raise ValueError('Live owner heartbeat expired')
    return d
def validate_frame(raw,d):
    from .core import validate_poses
    f=motion.decode(raw)
    fields={'schema_version','job_id','nonce','process_id','producer','physics_input_hash','coordinate_system','units','sequence','step','time','phase','bodies','positions','rotations'}
    motion.exact(f,fields|({'ready_status'} if 'ready_status' in f else set()))
    if f.get('ready_status','not_requested') not in ('waiting','acknowledged','timeout','not_requested'):raise ValueError('Live viewer-ready status')
    if type(f['schema_version']) is not int or f['schema_version']!=1 or f['job_id']!=d['job_id'] or f['nonce']!=d['nonce'] or type(f['process_id']) is not int or f['process_id']!=d['pid'] or d['pid']<=0 or f['producer']!=d['producer'] or f['physics_input_hash']!=d['physics_input_hash']:raise ValueError('Live frame active owner/producer/nonce/physics binding differs')
    if f['coordinate_system']!='RH_Z_UP' or f['units']!='meters' or f['phase'] not in ('simulate','baking'):raise ValueError('Live frame coordinate/phase')
    motion.integer(f['step'],0,14400);motion.integer(f['sequence'],1,14401)
    if f['sequence']!=f['step']+1 or type(f['time']) not in (int,float) or not math.isfinite(f['time']) or f['time']!=f['step']/d['solver_hz']:raise ValueError('Live actual step/time sequence')
    bodies=f['bodies']
    if type(bodies) is not list or len(bodies)>5000 or type(f['positions']) is not list or type(f['rotations']) is not list or len(f['positions'])!=len(bodies) or len(f['rotations'])!=len(bodies):raise ValueError('Live latest pose budget/shape')
    known={a['asset_id']:a for a in d['assets']};poses=[]
    for b,p,q in zip(bodies,f['positions'],f['rotations']):
        motion.exact(b,('id','asset_id','scale'))
        if b['asset_id'] not in known or type(b['scale']) not in (int,float) or struct.pack('<d',b['scale'])!=struct.pack('<d',known[b['asset_id']]['scale']):raise ValueError('Live body/asset uniform scale')
        poses.append(dict(b,position=p,rotation=q))
    validate_poses(poses,[dict(asset_id=a) for a in known],allow_empty=True)
    return f
def state(jobs,kind,expected=None,prefix='/api/live'):
    try:
        d=registration(jobs,kind,expected)
        if d is None:return dict(status='idle',job_id=None,token=None,sequence=None,frame=None,assets=[],region=None,error=None)
        value=dict(status=d['status'],job_id=d['job_id'],token=d['token'],sequence=None,frame=None,assets=[],region=d['region'],error=None)
        if d['status'] not in ('starting','running'):return value
        job=d['job_id'];token=d['token'];root=Path(os.path.abspath(jobs));run=motion.owned(root/'runs'/job,root)
        for a in d['assets']:
            query='?job='+job+'&token='+token+'&asset='+a['asset_id']
            value['assets'].append(dict(asset_id=a['asset_id'],geometry_url=prefix+'/geometry'+query,render_url=prefix+'/render'+query if a['render'] else None))
        if not d['pid']:return value
        path=motion.owned(run/'live-frame-v1.json',root)
        if not io_path(path).exists():return value
        info=io_path(path).stat();stamp=(d['job_id'],d['token'],d['pid'],d['physics_input_hash'],d['producer']['binary_sha256'],info.st_mtime_ns,info.st_ctime_ns,info.st_size,getattr(info,'st_ino',0))
        key=str(root);cached=_cache.get(key)
        if cached and cached[0]==stamp:f=cached[1]
        else:
            raw=read(path,motion.MAX_BYTES);f=validate_frame(raw,d)
            if cached and cached[0][:2]==stamp[:2] and f['sequence']<cached[1]['sequence']:raise ValueError('Live stale/reordered sequence')
            if cached and cached[0][:2]==stamp[:2] and f['bodies']!=cached[1]['bodies']:raise ValueError('Live same-run body identity/order changed')
            if len(_cache)>=4 and key not in _cache:_cache.pop(next(iter(_cache)))
            _cache[key]=(stamp,f)
        value.update(status='baking' if f['phase']=='baking' else 'running',sequence=f['sequence'],frame=f);return value
    except (ValueError,OSError,KeyError,TypeError,OverflowError) as error:
        return dict(status='error',job_id=None,token=None,sequence=None,frame=None,assets=[],region=None,error=str(error)[:400])
def asset(jobs,kind,job,token,aid,render=False,expected=None):
    d=registration(jobs,kind,expected)
    if d is None or d['status'] not in ('starting','running') or (d['job_id'],d['token'])!=(mask_source.run_id(job),mask_source.run_id(token)):raise ValueError('Inactive/stale live asset request')
    rows=[a for a in d['assets'] if a['asset_id']==mask_source.run_id(aid)]
    if len(rows)!=1:raise ValueError('Unknown live asset')
    a=rows[0];root=Path(os.path.abspath(jobs));run=motion.owned(root/'runs'/job,root)
    if render:
        if a['render'] is None:raise ValueError('Live source has no sealed render material')
        path=motion.owned(a['render']['path'],run)
        if path!=run/'inputs/review-assets'/aid/'scene.glb':raise ValueError('Live fixed render path')
        h=a['render']['sha256'];limit=64*1024*1024
    else:
        path=motion.owned(a['geometry_path'],root);h=a['content_hash'];limit=32*1024*1024
        wanted=run/'inputs/review-assets'/aid/'physics.obj' if kind=='normal' else root/'assets'/(h+'.obj')
        if path!=wanted:raise ValueError('Live fixed geometry path')
    raw=read(path,limit)
    if motion.digest(raw)!=h:raise ValueError('Live sealed asset bytes changed')
    return raw

def ready(jobs,kind,job,token,sequence,expected=None):
    if type(sequence) is not int or sequence!=1:raise ValueError('Ready only acknowledges the actual initial frame')
    d=registration(jobs,kind,expected)
    if d is None or (d['job_id'],d['token'])!=(mask_source.run_id(job),mask_source.run_id(token)):raise ValueError('Stale viewer-ready job/token')
    value=state(jobs,kind,expected)
    if value['status'] not in ('running','baking') or value['frame'] is None:return dict(status=value['status'],acknowledged=False)
    frame=value['frame']
    if frame.get('ready_status')!='waiting':return dict(status=frame.get('ready_status','not_requested'),acknowledged=False)
    if frame['step']!=0 or frame['sequence']!=1:raise ValueError('Viewer-ready initial observation changed')
    root=Path(os.path.abspath(jobs));run=motion.owned(root/'runs'/job,root);path=motion.owned(run/'live-ready-v1.json',root)
    ack=dict(schema_version=1,job_id=job,nonce=token,sequence=1)
    if io_path(path).exists():
        if motion.decode(read(path,512))!=ack:raise ValueError('Conflicting existing viewer-ready acknowledgement')
    else:atomic(path,ack,root)
    return dict(status='acknowledged',acknowledged=True)
