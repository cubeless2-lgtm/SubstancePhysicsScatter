"""Validate once, then recheck exact raw SHA before reusing a current bundle."""
import hashlib,io,json
from pathlib import Path
from PIL import Image
from substance_physics_scatter.fileio import io_path,logical_path
from substance_physics_scatter import compat,motion
import review_contract as n1,pbr_contract as n2,job_assets,height_field

PRODUCERS={
 '0.4.0-review.1':('22e437137c077fa985b8298b96486812009af77e2ee3f1cf4205705c4523b338','95dd1a2e893872c1f889cea0f2a545f497b3f5a44d79f3fb2f5c9d8e8052a572'),
 '0.4.0-review.2':('cc2df0c314f11e19b8f486d87447e0a13bcd7ad170f61dab7c14cfa720bdc869','6f8e2bc65bd558a6d2a28f5c1783c91c8fbe1f61122f1b643d338fd830cacfa5'),
 '0.4.0-review.3':('af57b7c68f7a42172e893663b98ee8fd5a07b76c9b34f4917f64431e0bfaf1d4','2494fde6074581771ce708c97770614f604097ff00951ac9e21ab5818675b7af')}
_cache=None
MOTION_PRODUCERS={
 '0.4.0-review.2':('3fc6bfacaecac6b40da70828c06db9e34166cab66c37cb49e2bc5c7e8a6603c6','7ab7b742188d110ab5cdfd68bfbdaf2e20691c41c88f68aedd30e3f2a1a72aa6'),
 '0.4.0-review.3':('9438f8e88c7071a6fa1e726b9f82307d48d4864976b403350303aa1be7dd48e2','e3e170aabbf687b1aa2cfa6e303cc8244e87cb79d4c83a2bf70d6fd5060bc8f5')}
LIVE_PRODUCERS={
 '0.4.0-review.2':('93793019f5549db80e8235274d4a3f874110282540af980b6a9afacb746a3fd8','8fa5a777bd41050729037c368a79126afadfd7c234ac7ae633cbfb820581d098'),
 '0.4.0-review.3':('21894422682a0455762dcd0bdd2ca0d4c3432a1d7e904d15e08720c8a8d72527','d0703a1aa38c23300c7dd3cac77d731413855dae35a0ca5e5515dbda5eb2daa3')}
LIVE_PREVIOUS_PRODUCERS=LIVE_PRODUCERS.copy()
LIVE_PRODUCERS={
 '0.4.0-review.2':('1b613147a7c08a2b91202cd3bab84a5c4eb5dd6bb20e8ab9cec98cb272f358d2','e2fe4cbabd63f46c10f0b728d48e2fa9a07cee4686d0978217d202aa8abd5a96'),
 '0.4.0-review.3':('c70ff545e18c153679a2d45e3a6848f6a59effd2f4a001c84682be8d61a19a79','6b48cb93dd09e2f1035ae7919cd9815dc91d8e164d5f6003be420041cef74320')}
def sha(raw):return hashlib.sha256(raw).hexdigest()

def check_watch(watch,work):
    for path,(expected,size) in watch.items():
        raw=n2.read(job_assets.owned(path,work),size)
        if len(raw)!=size or sha(raw)!=expected:raise ValueError('Validated job bytes changed; result is not served')

def check_result_snapshot(raw_result,c,root,sealed):
    """Only Jobs.current's exact owned OBJ cache alias may differ from native bytes.

    Run before promotion too, so the eventual getter cannot select a missing or
    corrupt core cache. No source/result/request dictionary is rewritten here.
    """
    snapshot=c['result'];same=raw_result==snapshot
    if same and not (c.get('local_review') or {}).get('source_closure'):return
    if type(raw_result) is not dict or type(snapshot) is not dict or set(raw_result)!=set(snapshot) or 'assets' not in raw_result:raise ValueError('Current result snapshot differs')
    def same_json(a,b):return json.dumps(a,sort_keys=True,allow_nan=False,separators=(',',':'))==json.dumps(b,sort_keys=True,allow_nan=False,separators=(',',':'))
    if not same_json({k:v for k,v in raw_result.items() if k!='assets'},{k:v for k,v in snapshot.items() if k!='assets'}):raise ValueError('Current result snapshot differs')
    originals=raw_result['assets'];visible=snapshot['assets'];requested=c['request'].get('assets')
    if any(type(rows) is not list for rows in (originals,visible,requested)) or not 1<=len(originals)<=6 or len(originals)!=len(visible) or len(originals)!=len(requested):raise ValueError('Current result asset closure differs')
    seen=set()
    for native,shown,request in zip(originals,visible,requested):
        if any(type(row) is not dict or type(row.get('path')) is not str for row in (native,shown,request)):raise ValueError('Current result asset fields differ')
        payload={k:v for k,v in native.items() if k!='path'}
        if any(not same_json({k:v for k,v in row.items() if k!='path'},payload) for row in (shown,request)):raise ValueError('Current result asset fields differ')
        aid=payload.get('asset_id');digest=n2.hexsha(payload.get('content_hash'))
        if type(aid) is not str or len(aid)!=32 or any(ch not in '0123456789abcdef' for ch in aid) or aid in seen:raise ValueError('Current result asset identity differs')
        seen.add(aid)
        source=root/'inputs/review-assets'/aid/'physics.obj';cache=root.parent.parent/'assets'/(digest+'.obj')
        if logical_path(native['path'])!=source or logical_path(shown['path']) not in (source,cache) or logical_path(request['path'])!=logical_path(shown['path']):raise ValueError('Current result asset cache alias differs')
        sealed(job_assets.owned(native['path'],root),digest,256*1024*1024)
        # This cache address is exactly compat.cache_path(jobs.directory, hash).
        sealed(job_assets.owned(cache,root.parent.parent),digest,256*1024*1024)
def get(candidate,work):
    global _cache
    key=sha(json.dumps(candidate,sort_keys=True,allow_nan=False).encode())
    cached=_cache
    if cached and cached['key']==key and not cached.get('hull_unverified'):
        try:
            check_watch(cached['watch'],work)
            return cached
        except (ValueError,OSError):
            if cached.get('hull_status')!='inherited':raise
            # Rebuild to distinguish changed PBR inputs from unavailable Hull
            # origin; only the latter can become an explicit absent branch.
    c=candidate;job=c['job_id'];root=job_assets.owned(Path(c['result_path']).parent,work)
    if root.name!=job or root.parent.name!='runs' or logical_path(c['result_path'])!=root/'result.json':raise ValueError('Current result owner')
    watch={}
    def observe(path,raw):
        p=str(logical_path(path));entry=(sha(raw),len(raw))
        if p in watch and watch[p]!=entry:raise ValueError('Conflicting bundle byte identity')
        watch[p]=entry
    def sealed(path,expected,limit=n2.LIMIT,byte_count=None):
        raw=n2.read(path,limit)
        if sha(raw)!=expected or (byte_count is not None and len(raw)!=byte_count):raise ValueError('Sealed bundle byte identity differs')
        observe(path,raw)
        return raw
    result_raw=n2.read(root/'result.json',16*1024*1024);observe(root/'result.json',result_raw)
    check_result_snapshot(n2.rawjson(result_raw),c,root,sealed)
    saved=c.get('local_review') or {};review=saved.get('review');doc=None;hulls=None;decoded={};original={};descriptors={}
    if review:
        n2.exact(review,('event','build_fingerprint','binary_sha256'));ref=review['event']['review'];side_raw=sealed(root/'review-v1.json',ref['sha256'],byte_count=ref['bytes']);side=n2.rawjson(side_raw);implementation=side['producer']['implementation_version']
        producer_pair=(review['build_fingerprint'],review['binary_sha256'])
        if implementation not in PRODUCERS or producer_pair not in (PRODUCERS.get(implementation),MOTION_PRODUCERS.get(implementation),LIVE_PRODUCERS.get(implementation),LIVE_PREVIOUS_PRODUCERS.get(implementation)):raise ValueError('Unapproved review producer')
        if implementation=='0.4.0-review.1':doc,hulls=n1.validate(root,review['event'],c['request'],*producer_pair)
        else:doc,decoded=n2.validate_artifacts(root,review['event'],c['request'],*producer_pair)
        if doc!=side or sha(result_raw)!=doc['result_sha256']:raise ValueError('Validated sidecar/result snapshot differs')
        mp=Path(c['request']['review_v1']['manifest_path']);sealed(mp,c['request']['review_v1']['manifest_sha256'],1024*1024)
        if 'hulls' in doc['artifacts']:
            row=doc['artifacts']['hulls'];hr=sealed(root/'hulls-v1.json',row['byte_sha256'],byte_count=row['byte_count']);hulls=n2.rawjson(hr)
        for role,row in doc['artifacts'].items():
            if role=='hulls':continue
            raw=sealed(root/row['path'],row['byte_sha256'],byte_count=row['byte_count']);original[role]=raw;descriptors[role]=dict(row,semantic='canonical XY/Z-up object-space direction' if role=='normal_material' else 'color' if role=='basecolor' else 'data')
    closure=saved.get('source_closure')
    if closure:
        n2.exact(closure,('path','sha256'));path=job_assets.owned(closure['path'],root);raw=n2.read(path,1024*1024)
        if sha(raw)!=closure['sha256']:raise ValueError('Job closure index SHA')
        index=n2.rawjson(raw)
        if index['version']!=1 or type(index['files']) is not list or len(index['files'])>256:raise ValueError('Job closure schema/budget')
        job_assets.verify(index,work);observe(path,raw)
        for item in index['files']:
            p=str(logical_path(item['path']));entry=(item['sha256'],item['bytes'])
            if p in watch and watch[p]!=entry:raise ValueError('Conflicting sealed closure byte identity')
            watch[p]=entry
    for aid,pin in saved.get('asset_renders',{}).items():
        raw=n2.read(job_assets.owned(pin['glb_path'],work),64*1024*1024)
        if sha(raw)!=pin['glb_sha256']:raise ValueError('Stored render revision differs')
        observe(pin['glb_path'],raw)
    if set(c['files'])!={'height','normal','coverage'} or set(c['hashes'])!={'height','normal','coverage'}:raise ValueError('HNC file set')
    res=c['request']['bake']['resolution'];height_meta=None;height_le=None
    for role in ('height','normal','coverage'):
        path=root/(role+'.png')
        if logical_path(c['files'][role])!=path:raise ValueError('HNC path identity')
        raw=n2.read(path,32*1024*1024)
        if sha(raw)!=c['hashes'][role]:raise ValueError('HNC raw SHA')
        observe(path,raw);original[role]=raw
        if role=='height':
            height_meta,height_le=height_field.decode(raw);w,h=height_meta['width'],height_meta['height'];bits=16;color='GREY'
        else:
            parsed=n2.png(raw);decoded[role]=parsed;w,h=parsed['width'],parsed['height'];bits=8;color='RGB' if role=='normal' else 'GREY'
            if parsed['mode']!=('RGB' if role=='normal' else 'L'):raise ValueError('HNC PNG channel type')
        if w!=res or h!=res:raise ValueError('HNC resolution')
        descriptors[role]=dict(path=path.name,byte_sha256=sha(raw),byte_count=len(raw),format='PNG',width=w,height=h,bit_depth=bits,color_type=color,color_space='linear',semantic='geometric canonical XY/Z-up object-space direction' if role=='normal' else 'world height' if role=='height' else 'coverage')
    sim=c['request']['simulation'];bake=c['request']['bake'];height_meta.update(job_id=job,height_min=bake['height_min'],height_max=bake['height_max'],region_width=sim['width'],region_depth=sim['depth'],coordinate_system='RH_Z_UP',units='meters')
    periodic=None
    if c['request'].get('physics_input_format_version')==3:
        if not doc or doc['producer']['implementation_version']!='0.4.0-review.3' or n2.implementation_for_request(c['request'])!='0.4.0-review.3':raise ValueError('Verified N3 periodic producer required')
        periodic=compat.periodic_identity(c['request'].get('periodic'));height_meta['periodic']=periodic
    for role,descriptor in descriptors.items():
        descriptor['url']=f'/api/maps/{job}/{role}'
        if role in ('normal','normal_material'):descriptor['normal_convention']=bake['normal'];descriptor['normal_space']='object/canonical XYZ'
        if role=='height':descriptor.update(height_min=bake['height_min'],height_max=bake['height_max'])
    hull_status='direct' if hulls is not None else 'absent';inherited=None;hull_reason=saved.get('hull_reason');hull_unverified=False
    if hulls is None and saved.get('inherited_hull'):
        import stored_hulls
        try:
            inherited=stored_hulls.validate(c,work,saved['inherited_hull']);hulls=inherited['hulls'];hull_status='inherited';watch.update(inherited['watch'])
        except (ValueError,OSError,KeyError,TypeError) as error:
            hull_unverified=True;hull_reason='검증 Hull 없음: '+str(error)[:300]
    observed_motion=motion.collect(root.parent.parent,c)
    for name,entry in observed_motion['watch'].items():
        if name in watch and watch[name]!=entry:raise ValueError('Motion/source closure byte conflict')
        watch[name]=entry
    value=dict(key=key,watch=watch,doc=doc,periodic=periodic,hulls=hulls,hull_status=hull_status,inherited=inherited,hull_reason=hull_reason,hull_unverified=hull_unverified,original=original,descriptors=descriptors,decoded=decoded,height_meta=height_meta,height_le=height_le,motion=observed_motion)
    # Never learn a replacement baseline between validation and cache publication.
    # Responses retain the bytes checked above; this scan only rejects changes.
    check_watch(watch,work)
    _cache=value
    return value

def normal_preview(raw):
    parsed=n2.png(raw)
    if parsed['mode']!='RGB':raise ValueError('Normal RGB required')
    image=Image.frombytes('RGB',(parsed['width'],parsed['height']),parsed['pixels']);r,g,b=image.split();image=Image.merge('RGB',(r,g.point(lambda v:255-v),b));out=io.BytesIO();image.save(out,format='PNG',icc_profile=None);return out.getvalue()
