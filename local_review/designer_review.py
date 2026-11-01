"""Closed, read-only Designer Graph example snapshots. No Jobs mutation/producer."""
from pathlib import Path
import hashlib,json,math,os,re,stat,struct,sys,uuid,threading,copy
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/'plugin') not in sys.path:sys.path.insert(0,str(ROOT/'plugin'))
import height_field
import pbr_contract
from substance_physics_scatter import motion

SOURCE_ROOT=ROOT/'output/GraphMaskReview'
LATEST=SOURCE_ROOT/'latest.json'
MAX_FILE=16*1024*1024
MAX_TOTAL=64*1024*1024
MAX_FILES=32
_cache={}
_sync_lock=threading.Lock()
_sync_records={}


def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode('utf8')
def doc(raw):return pbr_contract.rawjson(raw)
def exact(value,keys):pbr_contract.exact(value,keys)
def run_id(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{32}',value):raise ValueError('Review job/directory ID differs')
    return value


def owned(path,root):
    root=Path(os.path.abspath(root));path=Path(os.path.abspath(path))
    if not path.is_relative_to(root):raise ValueError('Designer review path escapes its owner')
    anchor=ROOT if root.is_relative_to(ROOT) else root
    cursor=anchor
    for part in ('',*path.relative_to(anchor).parts):
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('Designer review symlink forbidden')
        try:attributes=getattr(cursor.lstat(),'st_file_attributes',0)
        except FileNotFoundError:continue
        if attributes & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):raise ValueError('Designer review reparse point forbidden')
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Designer review resolved path escapes owner')
    return path


def read(path,limit=MAX_FILE):
    path=Path(path)
    if not path.is_file() or not 0<=path.stat().st_size<=limit:raise ValueError('Designer review file missing/over budget')
    with path.open('rb') as stream:raw=stream.read(limit+1)
    if len(raw)>limit:raise ValueError('Designer review bounded read exhausted')
    return raw


def geometry(raw):
    """Native OBJ float32 positions and original oriented triangles; no recenter."""
    if len(raw)>8*1024*1024:raise ValueError('OBJ byte budget')
    vertices=[];faces=[];normals=0;uvs=0
    for line in raw.decode('utf8').splitlines():
        values=line.split()
        if not values or values[0].startswith('#'):continue
        key=values[0]
        if key in ('v','vn','vt'):
            if (key in ('v','vn') and len(values)!=4) or (key=='vt' and len(values) not in (3,4)):raise ValueError('OBJ coordinate shape')
            numbers=[float(v) for v in values[1:]]
            if any(not math.isfinite(v) for v in numbers):raise ValueError('Nonfinite OBJ value')
            if key=='v':
                point=[struct.unpack('<f',struct.pack('<f',v))[0] for v in numbers]
                if any(not math.isfinite(v) for v in point):raise ValueError('OBJ float32 overflow')
                vertices.append(point)
            elif key=='vn':normals+=1
            else:uvs+=1
        elif key=='f':
            if len(values)!=4:raise ValueError('Review OBJ must already be triangles')
            face=[]
            for token in values[1:]:
                parts=token.split('/')
                if not 1<=len(parts)<=3 or not parts[0]:raise ValueError('OBJ corner syntax')
                for i,text in enumerate(parts):
                    if not text:continue
                    index=int(text);count=(len(vertices),uvs,normals)[i]
                    index=index-1 if index>0 else count+index
                    if not text.lstrip('-').isdigit() or int(text)==0 or not 0<=index<count:raise ValueError('OBJ corner index outside declaration')
                    if i==0:face.append(index)
            faces.append(face)
        elif key not in ('o','g','s','mtllib','usemtl'):raise ValueError('Unknown OBJ directive')
        if len(vertices)>100000 or len(faces)>=5000:raise ValueError('Review geometry budget')
    if not vertices or not faces:raise ValueError('Empty review geometry')
    return dict(coordinate_system='RH_Z_UP',units='meters',origin_shift=[0,0,0],scale_applied=1,
                positions=vertices,indices=[i for f in faces for i in f],triangles=len(faces),
                bounds=dict(min=[min(p[k] for p in vertices) for k in range(3)],max=[max(p[k] for p in vertices) for k in range(3)]))


def locator():
    """The original preparation pointer identifies a target, never its newest job."""
    latest_raw=read(owned(LATEST,SOURCE_ROOT),32768);latest=doc(latest_raw)
    exact(latest,('directory','guide','source','target','report','job_id'))
    directory=owned(latest['directory'],SOURCE_ROOT)
    if directory.parent!=SOURCE_ROOT:raise ValueError('Example directory is not a direct owned child')
    run_id(directory.name);run_id(latest['job_id']);target=latest['target']
    exact(target,('package_path','package_uid','graph_identifier','graph_url'))
    if not re.fullmatch('scatter_[0-9a-f]{32}',target['graph_identifier']):raise ValueError('Example graph identifier')
    for field,expected in (('report',directory/'report.json'),('guide',directory/'사용순서.txt'),('source',directory/'source/Source.sbs')):
        if owned(latest[field],directory)!=expected:raise ValueError('Fixed example locator differs')
    if owned(target['package_path'],directory)!=directory/'Scatter.sbs':raise ValueError('Fixed target locator differs')
    uuid.UUID(target['package_uid'].strip('{}'))
    jobs=directory/'Scatter_PhysicsScatter'/target['graph_identifier']
    return latest_raw,latest,directory,jobs


def source_files():
    """Single OBJ/input2 Graph Sim or Saved HNC; up to5000 poses/2048 PNG."""
    from substance_physics_scatter import compat,graph_companion,maskio
    latest_raw,latest,directory,jobs=locator();target=latest['target']
    files={};watch={}
    def take(name,path,limit=MAX_FILE):
        path=owned(path,SOURCE_ROOT);raw=read(path,limit)
        if len(files)>=MAX_FILES or sum(len(v) for v in files.values())+len(raw)>MAX_TOTAL:raise ValueError('Review source closure budget')
        files[name]=raw;watch[str(path)]=dict(sha256=digest(raw),bytes=len(raw));return raw
    files['raw/latest.json']=latest_raw;watch[str(LATEST)]=dict(sha256=digest(latest_raw),bytes=len(latest_raw))
    report=doc(take('raw/report.json',directory/'report.json',2*1024*1024))
    if report['status']!='GRAPH_MASK_REVIEW_READY' or report['target']!=target:raise ValueError('Prepared Designer example locator is not ready/bound')
    current=doc(take('raw/current.json',jobs/'current.json',2*1024*1024))
    job=run_id(current['job_id']);run=jobs/'runs'/job
    request=doc(take('raw/request.json',run/'request.json',2*1024*1024));result=doc(take('raw/result.json',run/'result.json',2*1024*1024))
    physical_raw=take('raw/physics_inputs.json',run/'physics_inputs.json',2*1024*1024)
    operation=request['operation']
    if operation not in ('simulate_bake','bake'):raise ValueError('Only input2 Sim or Saved HNC is supported')
    origin_ref=result['origin']['record_path']
    if origin_ref!='origin_result.json' and not (operation=='bake' and re.fullmatch(r'provenance/[0-9a-f]{64}\.json',origin_ref)):raise ValueError('Unknown origin reference')
    origin_raw=take('raw/'+origin_ref,owned(run/origin_ref,run),2*1024*1024)
    if digest(origin_raw)!=result['pose_origin']['record_sha256']:raise ValueError('Origin raw SHA differs')
    if operation=='bake':
        if owned(request['pose_source_path'],run)!=run/'pose_source.json':raise ValueError('Saved pose source locator differs')
        prior=take('raw/pose_source.json',run/'pose_source.json',2*1024*1024)
        if digest(prior)!=request['pose_source_hash']:raise ValueError('Saved pose source SHA differs')
    companion_raw=take('raw/graph_mask_source.json',run/'graph_mask_source.json',2*1024*1024)
    if current['job_id']!=job or owned(current['result_path'],directory)!=run/'result.json' or encoded(current['request'])!=encoded(request) or encoded(current['result'])!=encoded(result):raise ValueError('Raw request/result/current binding differs')
    if owned(request['output_directory'],directory)!=run or result['operation']!=operation or request['physics_input_format_version']!=2 or result['worker_version']!='0.3.0':raise ValueError('Only completed input2 HNC is supported')
    if result.get('status')!='completed' or not 0<=len(result['poses'])<=5000 or len(request['assets'])!=1:raise ValueError('Bounded single-asset example required')
    resolution=request['bake']['resolution']
    if type(resolution) is not int or resolution not in (64,128,256,512,1024,2048) or request['bake']['normal']!='OpenGL':raise ValueError('Supported HNC resolution/OpenGL required')
    if result['coordinate_system']!='RH_Z_UP' or result['units']!='meters' or result['pose_format_version']!=1:raise ValueError('Native pose coordinate/units differ')
    if digest(physical_raw)!=request['physics_input_hash'] or result['physics_input_hash']!=request['physics_input_hash']:raise ValueError('Physical raw SHA differs')
    # Existing compat/companion validation reads the mask too. Bound and collect
    # its exact owned bytes before either helper can enter maskio.read.
    mask_hash=pbr_contract.hexsha(request['scatter_mask']['content_hash'])
    if pbr_contract.hexsha(doc(companion_raw)['snapshot_sha256'])!=mask_hash:raise ValueError('Mask/companion SHA differs')
    mask_path=owned(request['scatter_mask']['path'],directory)
    if mask_path!=Path(maskio.cache_path(jobs,mask_hash)):raise ValueError('Mask cache locator differs')
    mask=take('raw/mask.png',mask_path,2*1024*1024)
    if digest(mask)!=mask_hash:raise ValueError('Mask bytes differ')
    # Collect only explicitly referenced, bounded host blobs before old readers.
    host_doc=doc(companion_raw);host_refs=set()
    if host_doc.get('pile_origin',{}).get('kind')=='blob':host_refs.add(pbr_contract.hexsha(host_doc['pile_origin']['sha256']))
    previous=host_doc.get('previous_source')
    if previous and previous.get('companion_available') is True:host_refs.add(pbr_contract.hexsha(previous['sha256']))
    if len(host_refs)>2:raise ValueError('Host provenance bound')
    for h in sorted(host_refs):
        raw=take('raw/host_provenance/'+h+'.json',owned(run/'host_provenance'/(h+'.json'),run),2*1024*1024)
        if digest(raw)!=h:raise ValueError('Host provenance SHA differs')
    wanted=compat.inputs(request['assets'],request['simulation'],request.get('scatter_mask'),2)
    bundle,blobs=compat.source(jobs,current,wanted)
    if bundle['poses']!=result['poses'] or len(blobs.paths)>(5 if operation=='bake' else 4):raise ValueError('Native source closure differs')
    # Original graph companion validates cached mask + authored history, without SDK.
    host=graph_companion.read(jobs,current)
    if host is None or host['raw']!=companion_raw or host['record']['mode']!=('saved_input' if operation=='bake' else 'current_graph_terminal'):raise ValueError('Graph mask companion required')
    capture_doc=host['record']
    if not capture_doc['capture_available']:
        origin=host['record']['pile_origin']
        if origin['kind']!='blob':raise ValueError('Saved Graph origin unavailable')
        capture_doc=graph_companion.document(doc(host['blobs'][origin['sha256']]))
    if not capture_doc['capture_available']:raise ValueError('Graph capture origin unavailable')
    for h,raw in host['blobs'].items():
        if raw!=files['raw/host_provenance/'+h+'.json']:raise ValueError('Host blob changed during validation')
    for path,h in blobs.paths.items():
        path=owned(path,directory)
        relative=path.relative_to(run).as_posix()
        if 'raw/'+relative not in files or blobs.data[h]!=files['raw/'+relative]:raise ValueError('Unexpected/changed native source reference')
    asset=request['assets'][0];asset_path=owned(asset['path'],directory)
    if asset_path!=jobs/'assets'/(asset['content_hash']+'.obj') or any(p['asset_id']!=asset['asset_id'] or p['scale']!=asset['scale'] for p in result['poses']):raise ValueError('Geometry cache/pose asset-scale binding differs')
    obj=take('raw/asset.obj',asset_path,8*1024*1024)
    if digest(obj)!=asset['content_hash']:raise ValueError('Native OBJ bytes differ')
    mesh=geometry(obj)
    source_sbs=take('raw/Source.sbs',directory/'source/Source.sbs',2*1024*1024)
    take('raw/Scatter.sbs',directory/'Scatter.sbs',2*1024*1024)
    for name in ('vertical_noise.sbs','invert.sbs'):take('raw/'+name,directory/'source/stock'/name,2*1024*1024)
    descriptors={};decoded={};height_meta=None;height_le=None
    exact(current['files'],('height','normal','coverage'));exact(current['hashes'],('height','normal','coverage'))
    for channel in ('height','normal','coverage'):
        if owned(current['files'][channel],directory)!=run/(channel+'.png') or result['maps'][channel]!=channel+'.png':raise ValueError('Exact map locator differs')
        raw=take('raw/'+channel+'.png',run/(channel+'.png'),MAX_FILE)
        if digest(raw)!=current['hashes'][channel]:raise ValueError('Original PNG SHA differs')
        if channel=='height':
            height_meta,height_le=height_field.decode(raw);w,h=height_meta['width'],height_meta['height'];bits=16;mode='GREY'
        else:
            parsed=pbr_contract.png(raw);decoded[channel]=parsed;w,h=parsed['width'],parsed['height'];bits=8;mode='RGB' if channel=='normal' else 'GREY'
            if parsed['mode']!=('RGB' if channel=='normal' else 'L'):raise ValueError('Native PNG channel layout differs')
        if (w,h)!=(resolution,resolution):raise ValueError('Native PNG resolution differs')
        descriptors[channel]=dict(width=w,height=h,bit_depth=bits,color_type=mode,color_space='linear',byte_sha256=digest(raw),byte_count=len(raw),
            semantic='canonical XY/Z-up object-space geometric direction' if channel=='normal' else 'height' if channel=='height' else 'coverage',url='/api/designer-review/maps/'+channel)
        if channel=='normal':descriptors[channel].update(normal_convention='OpenGL',normal_space='object/canonical XYZ')
    sim=request['simulation'];bake=request['bake']
    height_meta.update(job_id=job,height_min=bake['height_min'],height_max=bake['height_max'],region_width=sim['width'],region_depth=sim['depth'],coordinate_system='RH_Z_UP',units='meters')
    display=dict(job_id=job,pipeline='Designer Graph mask · legacy HNC · read-only',poses=result['poses'],geometry_url='/api/designer-review/geometry',
        geometry=dict(asset_id=asset['asset_id'],triangles=mesh['triangles'],bounds=mesh['bounds'],obj_sha256=digest(obj),origin_shift=[0,0,0],scale=asset['scale']),
        source=dict(source=latest['source'],target=target['package_path'],graph=capture_doc['capture']['selection']['graph_identifier'],terminal=capture_doc['capture']['selection']['terminal_identifier'],
                    disk_context=dict(current_file_sha256=digest(source_sbs),captured_disk_sha256=capture_doc['capture']['disk_file_sha256'],matches_capture_disk=digest(source_sbs)==capture_doc['capture']['disk_file_sha256'])),
        maps={k:v['url'] for k,v in descriptors.items()},map_descriptors=descriptors,height_field=dict(metadata_url='/api/designer-review/height',data_url='/api/designer-review/height/data'),
        settings=dict(snapshot=dict(simulation=sim,bake=bake)),hull_status='absent',PBR=False,read_only=True)
    observation=motion.collect(jobs,current);display['motion']=observation['metadata']
    if observation['raw'] is not None:
        source_job=observation['metadata']['source_job_id']
        # The loader later uses copied bytes only, never mutable original paths.
        source_motion=jobs/'runs'/source_job/'motion-v1.json'
        source_result=jobs/'runs'/source_job/'result.json'
        if take('raw/motion-v1.json',source_motion,motion.MAX_BYTES)!=observation['raw'] or take('raw/motion-origin-result.json',source_result)!=observation['source_result_raw']:raise ValueError('Motion changed between validation and snapshot copy')
        for name,(h,size) in observation['watch'].items():
            observed=dict(sha256=h,bytes=size)
            if name in watch and watch[name]!=observed:raise ValueError('Motion/source snapshot watch conflict')
            watch[name]=observed
    return job,files,watch,display,mesh,height_meta,height_le


def check_source_watch(watch):
    if type(watch) is not dict or not 1<=len(watch)<=MAX_FILES:raise ValueError('Designer source watch count')
    total=0
    for path,row in watch.items():
        exact(row,('sha256','bytes'));pbr_contract.hexsha(row['sha256'])
        if type(row['bytes']) is not int or not 0<=row['bytes']<=MAX_FILE:raise ValueError('Designer source watch size')
        total+=row['bytes']
        if total>MAX_TOTAL:raise ValueError('Designer source watch total')
        raw=read(owned(path,SOURCE_ROOT),min(row['bytes'],MAX_FILE))
        if len(raw)!=row['bytes'] or digest(raw)!=row['sha256']:raise ValueError('Designer source bytes changed; explicitly prepare a new snapshot')


def _atomic(path,raw,parent):
    path=owned(path,parent);temp=owned(parent/('publish-'+uuid.uuid4().hex+'.tmp'),parent)
    with temp.open('xb') as stream:stream.write(raw)
    temp.replace(path)


def _pointer(work):
    parent=owned(Path(work)/'designer-review',work);value=doc(read(owned(parent/'latest.json',parent),4096))
    exact(value,('version','job_id','manifest_sha256'))
    if type(value['version']) is not int or value['version']!=1:raise ValueError('Designer snapshot pointer version')
    run_id(value['job_id']);pbr_contract.hexsha(value['manifest_sha256']);return value


def _revisions(parent):
    path=owned(parent/'revisions.json',parent)
    if not path.exists():return {}
    value=doc(read(path,1024*1024));exact(value,('version','jobs'))
    if type(value['version']) is not int or value['version']!=1 or type(value['jobs']) is not dict or len(value['jobs'])>4096:raise ValueError('Snapshot revision index')
    for job,h in value['jobs'].items():run_id(job);pbr_contract.hexsha(h)
    return value['jobs']


def _commit(work,data):
    job,files,watch,display,mesh,height_meta,height_le=data
    parent=owned(Path(work)/'designer-review',work);parent.mkdir(exist_ok=True)
    final=owned(parent/job,parent)
    revisions=_revisions(parent)
    try:previous=_pointer(work)
    except (OSError,ValueError):
        if (parent/'latest.json').exists():raise
        previous=None
    if previous:
        old=previous['job_id'];h=previous['manifest_sha256']
        if old in revisions and revisions[old]!=h:raise ValueError('Previous revision seal conflict')
        revisions[old]=h
    if final.exists():
        sealed=load(work,job)
        if (sealed['display']['poses']!=display['poses'] or sealed['geometry']!=encoded(mesh)
                or any(sealed['maps'][role]!=files['raw/'+role+'.png'] for role in ('height','normal','coverage'))):raise ValueError('Immutable job changed; never overwrite')
        check_source_watch(watch)
        h=sealed['key']
        revisions[job]=h
        _atomic(parent/'revisions.json',encoded(dict(version=1,jobs=revisions)),parent)
        _atomic(parent/'latest.json',encoded(dict(version=1,job_id=job,manifest_sha256=h)),parent)
        return dict(job_id=job,directory=str(final),manifest_sha256=h,url='/designer-review/')
    stage=owned(parent/('.stage-'+uuid.uuid4().hex),parent);stage.mkdir(exist_ok=False)
    files.update({'display.json':encoded(display),'geometry.json':encoded(mesh),'height.json':encoded(height_meta),'height.u16le':height_le})
    if len(files)>MAX_FILES or sum(len(v) for v in files.values())>MAX_TOTAL:raise ValueError('Snapshot closure budget')
    entries=[]
    for name,raw in files.items():
        path=owned(stage/name,stage);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
        if digest(read(path))!=digest(raw):raise ValueError('Snapshot copy SHA differs')
        entries.append(dict(name=name,sha256=digest(raw),bytes=len(raw)))
    check_source_watch(watch)
    manifest=dict(version=2,kind='designer_graph_readonly',job_id=job,files=entries,source_watch=watch)
    raw=encoded(manifest)
    with (stage/'manifest.json').open('xb') as stream:stream.write(raw)
    stage.rename(final)
    if job in revisions and revisions[job]!=digest(raw):raise ValueError('Immutable revision seal conflict')
    revisions[job]=digest(raw)
    _atomic(parent/'revisions.json',encoded(dict(version=1,jobs=revisions)),parent)
    pointer=encoded(dict(version=1,job_id=job,manifest_sha256=digest(raw)))
    _atomic(parent/'latest.json',pointer,parent)
    return dict(job_id=job,directory=str(final),manifest_sha256=digest(raw),maps=display['maps'],poses=len(display['poses']),geometry_triangles=mesh['triangles'],url='/designer-review/')


def prepare(work):
    with _sync_lock:return _commit(work,source_files())


def pinned(display):
    value=copy.deepcopy(display);job=run_id(value['job_id']);query='?job='+job
    value['geometry_url']='/api/designer-review/geometry'+query
    value['height_field']=dict(metadata_url='/api/designer-review/height'+query,data_url='/api/designer-review/height/data'+query)
    value['motion']=motion.links(value.get('motion',motion.absent()),'/api/designer-review/motion/metadata'+query,'/api/designer-review/motion/data'+query)
    for role in ('height','normal','coverage'):
        url='/api/designer-review/maps/'+role+query;value['maps'][role]=url;value['map_descriptors'][role]['url']=url
    return value


def load(work,job=None):
    """Pinned, immutable copied closure only; original input changes are harmless."""
    parent=owned(Path(work)/'designer-review',work);pointer=_pointer(work)
    job=run_id(job or pointer['job_id']);expected=pointer['manifest_sha256'] if job==pointer['job_id'] else _revisions(parent).get(job)
    if expected is None:raise ValueError('Unknown Designer snapshot revision')
    root=owned(parent/job,parent);manifest_raw=read(owned(root/'manifest.json',root),1024*1024)
    if digest(manifest_raw)!=expected:raise ValueError('Designer manifest seal differs')
    manifest=doc(manifest_raw);exact(manifest,('version','kind','job_id','files','source_watch'))
    if type(manifest['version']) is not int or manifest['version'] not in (1,2) or manifest['kind']!='designer_graph_readonly' or manifest['job_id']!=job or type(manifest['files']) is not list or not 1<=len(manifest['files'])<=MAX_FILES:raise ValueError('Designer manifest identity/budget')
    values={};names=set();total=0
    stamps=[];members=[]
    for row in manifest['files']:
        exact(row,('name','sha256','bytes'));name=row['name'];pbr_contract.hexsha(row['sha256'])
        if type(name) is not str or '\\' in name or Path(name).is_absolute() or any(p in ('','..','.') for p in name.split('/')) or name.casefold() in names:raise ValueError('Designer duplicate/escaping member')
        names.add(name.casefold())
        if type(row['bytes']) is not int or not 0<=row['bytes']<=MAX_FILE:raise ValueError('Designer member size')
        total+=row['bytes']
        if total>MAX_TOTAL:raise ValueError('Designer total byte budget')
        path=owned(root/name,root);members.append((row,path))
        try:s=path.stat()
        except OSError as error:raise ValueError('Copied snapshot member unavailable') from error
        stamps.append((str(path),s.st_size,s.st_mtime_ns,s.st_ctime_ns,getattr(s,'st_ino',0)))
    cache_key=(str(root),expected);cached=_cache.get(cache_key)
    if cached is not None and cached['stamps']==stamps:return cached
    for row,path in members:
        name=row['name'];raw=read(path,row['bytes'])
        if len(raw)!=row['bytes'] or digest(raw)!=row['sha256']:raise ValueError('Designer copied bytes differ; no new baseline')
        values[name]=raw
    required={'display.json','geometry.json','height.json','height.u16le'}|{'raw/'+name for name in ('latest.json','report.json','current.json','request.json','result.json','physics_inputs.json','graph_mask_source.json','asset.obj','Source.sbs','Scatter.sbs','vertical_noise.sbs','invert.sbs','mask.png','height.png','normal.png','coverage.png')}
    extras=set(values)-required
    if not required<=set(values) or any(name not in ('raw/origin_result.json','raw/pose_source.json','raw/motion-v1.json','raw/motion-origin-result.json') and not re.fullmatch(r'raw/(host_provenance|provenance)/[0-9a-f]{64}\.json',name) for name in extras):raise ValueError('Designer snapshot exact file set differs')
    if ('raw/motion-v1.json' in values)!=('raw/motion-origin-result.json' in values):raise ValueError('Incomplete sealed Motion source')
    value=dict(key=expected,stamps=stamps,display=pinned(doc(values['display.json'])),geometry=values['geometry.json'],height=doc(values['height.json']),height_le=values['height.u16le'],
               maps={role:values['raw/'+role+'.png'] for role in ('height','normal','coverage')},pixels={role:pbr_contract.png(values['raw/'+role+'.png']) for role in ('normal','coverage')},motion=values.get('raw/motion-v1.json'))
    if value['motion'] is not None:
        verified=motion.validate(value['motion'],doc(values['raw/motion-origin-result.json']),digest(values['raw/motion-origin-result.json']),digest(values['raw/physics_inputs.json']))
        if value['display']['motion']!=motion.links(verified,'/api/designer-review/motion/metadata?job='+job,'/api/designer-review/motion/data?job='+job):raise ValueError('Motion display/sealed source binding differs')
    if value['display']['job_id']!=job or value['height']['job_id']!=job:raise ValueError('Pinned revision identity differs')
    if len(_cache)>=4:_cache.pop(next(iter(_cache)),None)
    _cache[cache_key]=value;return value


def pixel(snapshot,channel,x,y):
    if channel not in ('height','normal','coverage') or type(x) is not int or type(y) is not int:raise ValueError('Designer pixel bounds/channel')
    w=snapshot['height']['width'];h=snapshot['height']['height']
    if not 0<=x<w or not 0<=y<h:raise ValueError('Designer pixel bounds/channel')
    if channel=='height':
        value=struct.unpack_from('<H',snapshot['height_le'],2*(y*w+x))[0];meta=snapshot['height']
        return dict(values=[value],bit_depth=16,world_height=meta['height_min']+value/65535*(meta['height_max']-meta['height_min']))
    parsed=snapshot['pixels'][channel];count=3 if channel=='normal' else 1;at=(y*w+x)*count
    return dict(values=list(parsed['pixels'][at:at+count]),bit_depth=8,world_height=None)


def input_hint(record):
    """Cheap change detection only, never a validation baseline."""
    raw,latest,directory,jobs=locator();current=doc(read(owned(jobs/'current.json',directory),2*1024*1024));job=run_id(current['job_id']);run=jobs/'runs'/job;record['observed_job_id']=job
    paths={LATEST,Path(latest['report']),directory/'source/Source.sbs',directory/'Scatter.sbs',directory/'source/stock/vertical_noise.sbs',directory/'source/stock/invert.sbs',jobs/'current.json'}
    for name in ('request.json','result.json','physics_inputs.json','origin_result.json','pose_source.json','graph_mask_source.json','height.png','normal.png','coverage.png'):paths.add(run/name)
    paths.add(run/'motion-v1.json')
    motion_origin=current.get('result',{}).get('pose_origin',{}).get('job_id')
    if motion_origin:paths.add(jobs/'runs'/run_id(motion_origin)/'motion-v1.json')
    request=current['request']
    paths.add(owned(request['assets'][0]['path'],directory));paths.add(owned(request['scatter_mask']['path'],directory))
    result=current['result'];ref=result['origin']['record_path'];paths.add(owned(run/ref,run))
    try:companion=doc(read(owned(run/'graph_mask_source.json',run),2*1024*1024))
    except (OSError,ValueError):companion={}
    for value in (companion.get('pile_origin'),companion.get('previous_source')):
        if value and 'sha256' in value:paths.add(run/'host_provenance'/(pbr_contract.hexsha(value['sha256'])+'.json'))
    stamps=[]
    for path in sorted(paths,key=str):
        path=owned(path,SOURCE_ROOT)
        try:s=path.stat();value=(s.st_size,s.st_mtime_ns,s.st_ctime_ns,getattr(s,'st_ino',0))
        except FileNotFoundError:value=None
        stamps.append((str(path),value))
    return (job,tuple(stamps)),job


def state(work):
    """Only this GET syncs. Failures/cancellation leave the prior pointer intact."""
    key=str(Path(work).resolve());record=_sync_records.setdefault(key,dict(hint=None,status='ready',error=None,observed_job_id=None))
    if _sync_lock.acquire(blocking=False):
        try:
            try:
                hint,job=input_hint(record);record['observed_job_id']=job
            except (OSError,ValueError,KeyError,TypeError) as error:
                # Even malformed/truncated current JSON is retried only after its stat changes.
                try:
                    _,_,directory,jobs=locator();s=(jobs/'current.json').stat();hint=('invalid',s.st_size,s.st_mtime_ns,s.st_ctime_ns)
                except (OSError,ValueError,KeyError,TypeError):hint=('unavailable',)
                if hint!=record['hint']:record.update(hint=hint,status='error',error=type(error).__name__+': '+str(error)[:500])
            else:
                if hint!=record['hint']:
                    record['hint']=hint
                    try:
                        previous=None
                        try:previous=_pointer(work)['job_id']
                        except (OSError,ValueError):pass
                        data=source_files()
                        if data[0]!=job:raise ValueError('Current changed during synchronization; next poll will retry')
                        _commit(work,data)
                        record.update(status='updated' if previous!=job else 'ready',error=None)
                    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:record.update(status='error',error=type(error).__name__+': '+str(error)[:500])
        finally:_sync_lock.release()
        sync={k:record[k] for k in ('status','error','observed_job_id')}
    else:sync=dict(status='syncing',error=None,observed_job_id=record['observed_job_id'])
    display=copy.deepcopy(load(work)['display']);display['sync']=sync;return display
