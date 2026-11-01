"""Read-only, closed current-result ZIP export. Not a restore/import format."""
import copy,hashlib,io,json,re,zipfile
from pathlib import Path,PurePosixPath
from substance_physics_scatter import compat
import job_assets,result_bundle,pbr_contract as pbr

MAX_FILES=384
MAX_BYTES=512*1024*1024
MAX_ZIP_BYTES=512*1024*1024
FILE_BYTES=64*1024*1024
MAPS={'height','normal','coverage','basecolor','roughness','metallic','normal_material'}

def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
def member(name):
    if type(name) is not str or not name or '\\' in name or ':' in name or any(ord(c)<32 for c in name):raise ValueError('ZIP member path')
    parts=name.split('/')
    if PurePosixPath(name).is_absolute() or any(p in ('','.','..') or p.endswith((' ','.')) for p in parts):raise ValueError('ZIP member traversal/ambiguity')
    return name

class Archive:
    def __init__(self):self.files={};self.folded=set();self.total=0;self.rows=[]
    def add(self,name,raw,locator=None,expected=None):
        name=member(name)
        if name.casefold() in self.folded:raise ValueError('Duplicate ZIP member')
        if type(raw) is not bytes or len(raw)>FILE_BYTES or len(self.files)+1>MAX_FILES or self.total+len(raw)>MAX_BYTES:raise ValueError('ZIP file/aggregate budget')
        actual=digest(raw)
        if expected is not None and actual!=expected:raise ValueError('ZIP sealed SHA differs')
        self.folded.add(name.casefold());self.total+=len(raw);self.files[name]=raw
        self.rows.append(dict(archive_path=name,sha256=actual,bytes=len(raw),original_locator=locator))
    def pack(self):
        class Output(io.BytesIO):
            def write(self,data):
                if self.tell()+len(data)>MAX_ZIP_BYTES:raise ValueError('ZIP output budget')
                return super().write(data)
        output=Output()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=False) as z:
            for name,raw in self.files.items():z.writestr(name,raw)
        return output.getvalue()

def build(current,work):
    """Retain checked bytes, then reject any source change before returning ZIP."""
    c=copy.deepcopy(current);job=c['job_id']
    if type(job) is not str or re.fullmatch('[0-9a-f]{32}',job) is None:raise ValueError('ZIP job identity')
    root=job_assets.owned(Path(c['result_path']).parent,work)
    if root.name!=job or root.parent.name!='runs':raise ValueError('ZIP result owner')
    bundle=result_bundle.get(c,work)
    if set(bundle['original'])!=MAPS:raise ValueError('ZIP export requires a verified seven-map N2 result')
    archive=Archive();watch={};locations={}
    def load(path,expected,limit=FILE_BYTES):
        path=job_assets.owned(path,work);raw=pbr.read(path,min(limit,FILE_BYTES))
        if digest(raw)!=expected:raise ValueError('ZIP sealed SHA differs')
        key=str(path);entry=(expected,len(raw))
        if key in watch and watch[key]!=entry:raise ValueError('Conflicting export identity')
        watch[key]=entry;return path,raw
    def add_job(path,expected,limit=FILE_BYTES):
        path=job_assets.owned(path,root);name=member('job/'+path.relative_to(root).as_posix())
        if str(path) in locations:
            if locations[str(path)]!=(name,expected):raise ValueError('Conflicting export locator')
            return
        path,raw=load(path,expected,limit);archive.add(name,raw,str(path),expected);locations[str(path)]=(name,expected)
    # Bundle has already sealed result/sidecar/maps/closure/materials/used assets.
    # Core cache aliases may be watched but are not exported as additional sources.
    for path,(expected,size) in bundle['watch'].items():
        if Path(path).is_relative_to(root):add_job(path,expected,size)
    physical_path=root/'physics_inputs.json';_,physical_raw=load(physical_path,c['request']['physics_input_hash'],16*1024*1024)
    physical=pbr.rawjson(physical_raw)
    _,blobs=compat.source(root.parent.parent,c,physical)
    # This public pure validator follows only the protocol's hash references.
    for path,expected in blobs.paths.items():add_job(path,expected,16*1024*1024)
    # Saved bundles can point to earlier raw request/result/bundle blobs by SHA.
    # Follow only these closed protocol fields, never arbitrary JSON paths or hashes.
    visited=set()
    def provenance(expected,role,depth=0):
        pbr.hexsha(expected)
        if depth>64 or len(visited)>=128:raise ValueError('ZIP provenance budget')
        key=(expected,role)
        if key in visited:return
        visited.add(key)
        path=physical_path if expected==c['request']['physics_input_hash'] else root/'provenance'/(expected+'.json')
        try:add_job(path,expected,16*1024*1024)
        except FileNotFoundError as error:
            raise ValueError('현재 job에 필요한 과거 출처 raw가 포함되지 않아 ZIP을 내보낼 수 없습니다. 연속 Saved 전이자료 누락은 현재 지원 범위 밖이며 과거 폴더를 자동 탐색하지 않습니다.') from error
        doc=pbr.rawjson(archive.files[locations[str(path)][0]])
        if role=='bundle':
            for field in ('source_input_sha256','source_request_sha256','source_pose_source_sha256'):
                if field in doc:provenance(doc[field],'bundle' if field=='source_pose_source_sha256' else 'raw',depth+1)
            for field in ('origin','source'):
                if field in doc:provenance(doc[field]['record_sha256'],'result' if field=='source' else 'raw',depth+1)
            for step in doc.get('legacy_chain',[]):
                for field in ('request_sha256','result_sha256','key_material_sha256'):provenance(step[field],'raw',depth+1)
            check_saved_source(doc)
    def check_saved_source(bundle):
        if 'source' not in bundle or 'source_request_sha256' not in bundle:return
        def referenced(h):return pbr.rawjson(archive.files[locations[str(root/'provenance'/(h+'.json'))][0]])
        prior_result=referenced(bundle['source']['record_sha256'])
        if prior_result.get('operation')=='bake':
            prior_request=referenced(bundle['source_request_sha256'])
            # Native result deliberately has no pose_source_hash. The paired
            # request and the source bundle bind that exact prior bundle hash.
            prior_hash=bundle.get('source_pose_source_sha256')
            if prior_request.get('operation')!='bake' or type(prior_hash) is not str or prior_request.get('pose_source_hash')!=prior_hash:raise ValueError('ZIP Saved source/request bundle binding differs')
    if c['request']['operation']=='bake':
        add_job(root/'pose_source.json',c['request']['pose_source_hash'],16*1024*1024)
        prior=pbr.rawjson(archive.files['job/pose_source.json'])
        # Start with the sealed pose-source bytes under their literal path.
        for field in ('source_input_sha256','source_request_sha256','source_pose_source_sha256'):
            if field in prior:provenance(prior[field],'bundle' if field=='source_pose_source_sha256' else 'raw')
        for field in ('origin','source'):
            if field in prior:provenance(prior[field]['record_sha256'],'result' if field=='source' else 'raw')
        for step in prior.get('legacy_chain',[]):
            for field in ('request_sha256','result_sha256','key_material_sha256'):provenance(step[field],'raw')
        check_saved_source(prior)
    request_raw=archive.files['job/request.json'];request=pbr.rawjson(request_raw)
    result=pbr.rawjson(archive.files['job/result.json'])
    if set(request)!=set(c['request']):raise ValueError('ZIP request field set differs')
    for key,value in request.items():
        if key=='assets':
            if value!=result['assets']:raise ValueError('ZIP request asset closure differs')
        elif key in ('output_directory','physics_inputs_path','pose_source_path'):
            expected={'output_directory':root,'physics_inputs_path':physical_path,'pose_source_path':root/'pose_source.json'}[key]
            if Path(value)!=expected:raise ValueError('ZIP request owned locator differs')
        elif key=='scatter_mask' and value is not None:
            original=copy.deepcopy(value);visible=copy.deepcopy(c['request'][key]);path=job_assets.owned(original.pop('path'),root);visible.pop('path')
            if original!=visible or str(path) not in locations or locations[str(path)][1]!=value['content_hash']:raise ValueError('ZIP Mask closure differs')
        elif value!=c['request'][key]:raise ValueError('ZIP request snapshot differs')
    # Pointer/settings are distinct host provenance, never substitutes for raw JSON.
    pointer=job_assets.owned(root.parent.parent/'current.json',work);pointer_raw=pbr.read(pointer,16*1024*1024);pointer_doc=pbr.rawjson(pointer_raw)
    expected_pointer=copy.deepcopy(c);expected_pointer['request']=request;expected_pointer['result']=result
    if pointer_doc!=expected_pointer:raise ValueError('ZIP current pointer changed or differs')
    watch[str(pointer)]=(digest(pointer_raw),len(pointer_raw));archive.add('host/current-pointer.json',pointer_raw,str(pointer),digest(pointer_raw))
    archive.add('host/settings.json',encoded(c.get('local_review') or {}))
    archive.add('host/poses.json',encoded(result['poses']))
    hull=bundle.get('hull_status','direct' if bundle['hulls'] is not None else 'absent')
    readme=('Verified current-result export only; ZIP import/restore is not implemented.\n'
            'Raw request/result/sidecar/closure JSON and image bytes are unchanged.\n'
            'Original absolute locators remain inside raw JSON. manifest.json maps them to ZIP paths.\n'
            'Host settings/poses are separate copied projections; raw native result is authoritative.\n'
            'Coordinates: RH Z-up, meters. Height: original PNG16. Normal convention is in request/sidecar.\n'
            f'Hull status: {hull}. An inherited Hull includes its sealed direct-origin proof; no synthetic Hull is generated.\n'
            'Only the selected job closure and referenced provenance are included; no external directory scan.\n'
            'Export requires every referenced historical raw blob inside this job. Some repeated Saved jobs lack transitive blobs and are rejected; Saved rebaking itself remains supported.\n')
    archive.add('README.txt',readme.encode('utf-8'))
    # Manifest covers all payload entries (not its own impossible self hash).
    aliases={row['original_locator']:row['archive_path'] for row in archive.rows if row['original_locator'] is not None}
    closure=c.get('local_review',{}).get('source_closure')
    if closure:
        closure_doc=pbr.rawjson(archive.files[locations[str(Path(closure['path']))][0]])
        for item in closure_doc['files']:
            target=locations.get(str(Path(item['path'])))
            if target is None or target[1]!=item['sha256']:raise ValueError('ZIP closure mapping differs')
            alias=item['source_path']
            if alias in aliases and archive.files[aliases[alias]]!=archive.files[target[0]]:raise ValueError('Conflicting ZIP source alias')
            aliases.setdefault(alias,target[0])
    if closure:
        for row in closure_doc.get('source_aliases',[]):
            target=locations.get(str(Path(row['path'])))
            if target is None or target[1]!=row['sha256']:raise ValueError('ZIP historical source alias differs')
            if row['source_path'] in aliases and archive.files[aliases[row['source_path']]]!=archive.files[target[0]]:raise ValueError('ZIP historical source alias conflict')
            aliases.setdefault(row['source_path'],target[0])
    if bundle.get('inherited'):
        for row in bundle['inherited']['proof']['files']:
            target=locations.get(str(Path(row['path'])))
            if target is None or target[1]!=row['sha256']:raise ValueError('ZIP inherited Hull copy mapping differs')
            aliases.setdefault(row['source'],target[0])
    manifest=dict(version=1,kind='verified_result_export',job_id=job,hull_status=hull,hull_reason=bundle.get('hull_reason'),import_restore_supported=False,locator_mapping=aliases,files=copy.deepcopy(archive.rows))
    archive.add('manifest.json',encoded(manifest))
    result_bundle.check_watch(bundle['watch'],work)
    for path,(expected,size) in watch.items():load(path,expected,size)
    raw=archive.pack()
    # No changes observed during compression are accepted as a new baseline.
    result_bundle.check_watch(bundle['watch'],work)
    for path,(expected,size) in watch.items():load(path,expected,size)
    return raw
