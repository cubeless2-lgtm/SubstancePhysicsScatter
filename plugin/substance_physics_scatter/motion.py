"""Bounded actual Jolt observations. No SDK, interpolation or physics mutation."""
from pathlib import Path
import copy,hashlib,json,math,os,stat,struct
from . import compat,mask_source
from .fileio import io_path

MAX_BYTES=8*1024*1024
MAX_POSES=40000
MAX_FRAMES=3601
# Exact newly built observer identities, populated after the isolated build.
PRODUCERS={
 'b782dfec0b177d66a02e0f3ab731822bd214fdc8fe3c6eab1e670455f935921d':'ca75080da102a17ec44c6b4da240e41f0141cc8928142e54022d05c2a74c51bf',
 '3fc6bfacaecac6b40da70828c06db9e34166cab66c37cb49e2bc5c7e8a6603c6':'7ab7b742188d110ab5cdfd68bfbdaf2e20691c41c88f68aedd30e3f2a1a72aa6',
 '9438f8e88c7071a6fa1e726b9f82307d48d4864976b403350303aa1be7dd48e2':'e3e170aabbf687b1aa2cfa6e303cc8244e87cb79d4c83a2bf70d6fd5060bc8f5'}
PRODUCERS.update({
 'aa5238c8238e94ca115220584aa4f1c732d2b9762bd383f1b40b2f0eb303f136':'2fd5fb09ca4ee64f5e825db9696ffac00477dd059f708c7fca74ba39ba45c3ae',
 '93793019f5549db80e8235274d4a3f874110282540af980b6a9afacb746a3fd8':'8fa5a777bd41050729037c368a79126afadfd7c234ac7ae633cbfb820581d098',
 '21894422682a0455762dcd0bdd2ca0d4c3432a1d7e904d15e08720c8a8d72527':'d0703a1aa38c23300c7dd3cac77d731413855dae35a0ca5e5515dbda5eb2daa3'})
PRODUCERS.update({
 '910ac079f0c003a38a80d6ad5792b26262a9df3293e62de2b46a9eee54f118a1':'2c7bc9a8f790f407f0a962b5729a47b09df8ffeaa326e68295558ec337204cbf',
 '1b613147a7c08a2b91202cd3bab84a5c4eb5dd6bb20e8ab9cec98cb272f358d2':'e2fe4cbabd63f46c10f0b728d48e2fa9a07cee4686d0978217d202aa8abd5a96',
 'c70ff545e18c153679a2d45e3a6848f6a59effd2f4a001c84682be8d61a19a79':'6b48cb93dd09e2f1035ae7919cd9815dc91d8e164d5f6003be420041cef74320'})

def digest(raw):return hashlib.sha256(raw).hexdigest()
def absent(reason='이 결과에는 실제 낙하 기록이 없습니다.'):
    return dict(available=False,status='absent',reason=reason,source_job_id=None,final_poses_sha256=None,duration_seconds=0.,frame_count=0,body_count=0,sample_stride=0,metadata_url=None,data_url=None)
def owned(path,root):
    root=Path(os.path.abspath(root));path=Path(os.path.abspath(path))
    if path==root or not path.is_relative_to(root):raise ValueError('Motion path escapes fixed job owner')
    for part in (path,*path.parents):
        try:info=io_path(part).lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Motion reparse path rejected')
    return path
def read(path,limit=MAX_BYTES):
    path=io_path(path);size=path.stat().st_size
    if not path.is_file() or not 0<size<=limit:raise ValueError('Motion bounded file required')
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)!=size or path.stat().st_size!=size:raise ValueError('Motion source changed during read')
    return raw
def _pairs(rows):
    result={}
    for k,v in rows:
        if k in result:raise ValueError('Duplicate motion JSON field')
        result[k]=v
    return result
def decode(raw):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('Motion JSON exceeds8MiB')
    try:return json.loads(raw,object_pairs_hook=_pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite motion JSON')))
    except (RecursionError,UnicodeError) as error:raise ValueError('Motion JSON decoding bound') from error
def exact(value,fields):mask_source.fields(value,set(fields),'motion')
def integer(value,lo,hi):
    if type(value) is not int or not lo<=value<=hi:raise ValueError('Motion integer range/type')
    return value
def pose_hash(poses):
    raw=bytearray(b'motion-final-poses-v1\0'+struct.pack('<I',len(poses)))
    for p in poses:
        aid=p['asset_id'].encode('utf8');raw+=struct.pack('<II',integer(p['id'],0,0xffffffff),len(aid))+aid
        for value in [p['scale'],*p['position'],*p['rotation']]:
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Nonfinite motion pose')
            raw+=struct.pack('<d',value)
    return digest(raw)

def validate(raw,source_result,result_sha256,physics_input_hash):
    from .core import validate_poses
    data=decode(raw)
    exact(data,('schema_version','coordinate_system','units','source_job_id','result_sha256','physics_input_hash','pose_origin','producer','bodies','sampling','frames','final_poses_sha256'))
    if type(data['schema_version']) is not int or data['schema_version']!=1 or data['coordinate_system']!='RH_Z_UP' or data['units']!='meters':raise ValueError('Motion coordinate/version contract')
    producer=data['producer'];exact(producer,('implementation_version','build_fingerprint','binary_sha256'))
    if producer['implementation_version']!='0.4.0-motion.1' or PRODUCERS.get(mask_source.sha(producer['build_fingerprint']))!=mask_source.sha(producer['binary_sha256']):raise ValueError('Unapproved motion producer')
    if data['source_job_id']!=source_result['job_id'] or data['result_sha256']!=mask_source.sha(result_sha256) or data['physics_input_hash']!=mask_source.sha(physics_input_hash) or data['pose_origin']!=source_result['pose_origin']:raise ValueError('Motion raw source/physics/origin binding differs')
    if source_result.get('operation') not in ('simulate','simulate_bake') or source_result.get('status')!='completed' or source_result.get('coordinate_system')!='RH_Z_UP' or source_result.get('units')!='meters':raise ValueError('Motion requires a completed actual simulation')
    poses=source_result['poses'];bodies=data['bodies'];frames=data['frames'];sampling=data['sampling']
    if type(bodies) is not list or len(bodies)!=len(poses) or len(bodies)>5000:raise ValueError('Motion body identity count')
    for b,p in zip(bodies,poses):
        exact(b,('id','asset_id','scale'));integer(b['id'],0,0xffffffff)
        if type(b['scale']) not in (int,float) or not math.isfinite(b['scale']) or not 0<b['scale']<=100:raise ValueError('Motion body scale type/range')
        if b['id']!=p['id'] or b['asset_id']!=p['asset_id'] or struct.pack('<d',b['scale'])!=struct.pack('<d',p['scale']):raise ValueError('Motion body/asset/scale identity differs')
    exact(sampling,('solver_hz','substeps','stride','target_hz'))
    periodic=source_result.get('physics_input_format_version')==3;hz=60 if periodic else 120;substeps=16 if periodic else 1
    if any(type(sampling[k]) is not int for k in sampling) or (sampling['solver_hz'],sampling['substeps'],sampling['target_hz'])!=(hz,substeps,30):raise ValueError('Motion solver sampling contract')
    stride=integer(sampling['stride'],2 if periodic else 4,14400)
    if type(frames) is not list or not 1<=len(frames)<=MAX_FRAMES or len(frames)*len(bodies)>MAX_POSES:raise ValueError('Motion frame/pose budget')
    steps=integer(source_result['steps'],0,115200)
    if steps%substeps:raise ValueError('Motion periodic completed-step count')
    last_step=steps//substeps
    expected=[0]+list(range(stride,last_step+1,stride))
    if last_step!=expected[-1]:expected.append(last_step)
    if len(expected)!=len(frames):raise ValueError('Motion initial/sampled/final frame sequence')
    for f,step in zip(frames,expected):
        exact(f,('step','time','positions','rotations'));integer(f['step'],0,14400)
        if f['step']!=step or type(f['time']) not in (int,float) or not math.isfinite(f['time']) or f['time']!=step/hz:raise ValueError('Motion actual physics timestamp differs')
        if type(f['positions']) is not list or type(f['rotations']) is not list or len(f['positions'])!=len(bodies) or len(f['rotations'])!=len(bodies):raise ValueError('Motion frame body array differs')
        frame_poses=[dict(b,position=p,rotation=q) for b,p,q in zip(bodies,f['positions'],f['rotations'])]
        validate_poses(frame_poses,source_result['assets'],allow_empty=True)
    final=[dict(b,position=p,rotation=q) for b,p,q in zip(bodies,frames[-1]['positions'],frames[-1]['rotations'])]
    h=pose_hash(poses)
    if mask_source.sha(data['final_poses_sha256'])!=h or pose_hash(final)!=h:raise ValueError('Motion final frame/actual result pose bits differ')
    return dict(available=bool(bodies),status='available' if bodies else 'absent',reason=None if bodies else '생성된 body가 없어 낙하 기록이 없습니다.',source_job_id=data['source_job_id'],final_poses_sha256=h,duration_seconds=float(frames[-1]['time']),frame_count=len(frames),body_count=len(bodies),sample_stride=stride,metadata_url=None,data_url=None)

def collect(jobs_root,current):
    """Follow only the validated original Sim id inside the same owned jobs root."""
    result=current['result'];job=mask_source.run_id(current['job_id'])
    root=Path(os.path.abspath(jobs_root));run=owned(root/'runs'/job,root)
    origin=result.get('pose_origin')
    if not isinstance(origin,dict):return dict(metadata=absent(),raw=None,watch={})
    source_job=mask_source.run_id(origin['job_id']);source_run=owned(root/'runs'/source_job,root)
    path=owned(source_run/'motion-v1.json',root)
    if not io_path(path).exists():return dict(metadata=absent(),raw=None,watch={})
    watched={}
    def take(path,limit=16*1024*1024):
        path=owned(path,root);raw=read(path,limit);watched[str(path)]=(digest(raw),len(raw));return raw
    raw=take(path,MAX_BYTES)
    request=decode(take(run/'request.json'));physical_raw=take(run/'physics_inputs.json');wanted=compat.inputs(request['assets'],request['simulation'],request.get('scatter_mask'),request['physics_input_format_version'])
    bundle,blobs=compat.source(root,current,wanted)
    if bundle['origin']!=origin or pose_hash(bundle['poses'])!=pose_hash(result['poses']):raise ValueError('Motion current/validated pose origin differs')
    try:source_raw=take(source_run/'result.json');source_request_raw=take(source_run/'request.json')
    except FileNotFoundError:return dict(metadata=absent('원래 Sim 결과가 없어 실제 낙하 기록의 출처를 검증할 수 없습니다.'),raw=None,watch={})
    source=decode(source_raw);source_request=decode(source_request_raw)
    if source['job_id']!=source_job or source_request['job_id']!=source_job or source.get('operation') not in ('simulate','simulate_bake') or source_request.get('operation')!=source['operation'] or source['pose_origin']!=origin or pose_hash(source['poses'])!=pose_hash(result['poses']):raise ValueError('Motion original Sim identity differs')
    original,original_blobs=compat.source(root,dict(job_id=source_job),wanted)
    if original['origin']!=origin or original['source']['record_sha256']!=digest(source_raw):raise ValueError('Motion original source raw proof differs')
    for group in (blobs,original_blobs):
        for name,h in group.paths.items():
            observed=take(name)
            if digest(observed)!=h or observed!=group.data[h]:raise ValueError('Motion source changed during validation')
    if digest(physical_raw)!=source['physics_input_hash'] or source_request['physics_input_hash']!=source['physics_input_hash']:raise ValueError('Motion original/current physical bytes differ')
    metadata=validate(raw,source,digest(source_raw),digest(physical_raw))
    if any(digest(read(name,size))!=h for name,(h,size) in watched.items()):raise ValueError('Motion origin changed before adoption')
    return dict(metadata=metadata,raw=raw,watch=watched,source_result_raw=source_raw)

def links(metadata,metadata_url,data_url):
    value=copy.deepcopy(metadata)
    if value['available']:value.update(metadata_url=metadata_url,data_url=data_url)
    return value
