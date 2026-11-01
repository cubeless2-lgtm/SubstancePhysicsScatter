"""Bounded data-only FBX preflight, unit policy and source texture normalization."""
from pathlib import Path
import hashlib,io,math,ntpath,struct,zlib

def source_info(path):
    path=Path(path);size=path.stat().st_size
    if size>32*1024*1024:raise ValueError('FBX file budget before read')
    with path.open('rb') as stream:raw=stream.read(size+1)
    if len(raw)!=size:raise ValueError('FBX changed during read')
    if len(raw)>32*1024*1024 or raw[:23]!=b'Kaydara FBX Binary  \0\x1a\0':raise ValueError('Only bounded binary FBX is supported')
    version=struct.unpack_from('<I',raw,23)[0];wide=version>=7500;header=25 if wide else 13;count=0;array_total=0
    def node(at,depth):
        nonlocal count,array_total
        count+=1
        if depth>48 or count>30000 or at+header>len(raw):raise ValueError('FBX structure budget')
        end,nprops,propbytes=struct.unpack_from('<QQQ' if wide else '<III',raw,at);name_len=raw[at+header-1]
        if end==0:return None,at+header
        if not at+header+name_len<=end<=len(raw) or nprops>100000:raise ValueError('FBX node bounds')
        start=at+header;name=raw[start:start+name_len].decode('ascii');p=start+name_len;props=[];finish=p+propbytes
        if finish>end:raise ValueError('FBX property bounds')
        for _ in range(nprops):
            if p>=finish:raise ValueError('FBX missing property')
            tag=chr(raw[p]);p+=1
            if tag in 'YCIFDL':
                fmt={'Y':'h','C':'?','I':'i','F':'f','D':'d','L':'q'}[tag];size=struct.calcsize(fmt)
                if p+size>finish:raise ValueError('FBX scalar boundary')
                props.append(struct.unpack_from('<'+fmt,raw,p)[0]);p+=size
            elif tag in 'SR':
                if p+4>finish:raise ValueError('FBX string boundary')
                size=struct.unpack_from('<I',raw,p)[0];p+=4
                if p+size>finish:raise ValueError('FBX string size')
                data=raw[p:p+size];p+=size;props.append(data.decode('utf-8') if tag=='S' else data)
            elif tag in 'bcifdly':
                if p+12>finish:raise ValueError('FBX array header')
                length,encoding,size=struct.unpack_from('<III',raw,p);p+=12;expected=length*{'b':1,'c':1,'i':4,'f':4,'d':8,'l':8,'y':2}[tag];array_total+=expected
                if expected>64*1024*1024 or array_total>64*1024*1024 or p+size>finish:raise ValueError('FBX decoded array budget')
                data=raw[p:p+size];p+=size
                if encoding==1:
                    decoder=zlib.decompressobj();decoded=decoder.decompress(data,expected+1)
                    if len(decoded)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError('FBX compressed array size/trailer')
                elif encoding!=0 or size!=expected:raise ValueError('FBX array encoding/size')
                props.append(None)
            else:raise ValueError('Unknown FBX property encoding')
        if p!=finish:raise ValueError('FBX property byte count')
        children=[]
        while p+header<=end:
            child,next_at=node(p,depth+1)
            if child is None:p=next_at;break
            children.append(child);p=next_at
        if p!=end:raise ValueError('FBX node terminator boundary')
        return dict(name=name,props=props,children=children),end
    trees=[];at=27
    while at+header<=len(raw):
        item,at=node(at,0)
        if item is None:break
        trees.append(item)
    globals={};images=[];unsupported=[]
    def walk(n):
        if n['name']=='P' and n['props'] and n['props'][0] in ('UnitScaleFactor','OriginalUnitScaleFactor','UpAxis','UpAxisSign','FrontAxis','FrontAxisSign','CoordAxis','CoordAxisSign'):globals[n['props'][0]]=n['props'][-1]
        if n['name'] in ('AnimationStack','AnimationCurve','Deformer') or n['name']=='Model' and n['props'] and n['props'][-1] in ('LimbNode','Root'):unsupported.append(n['name'])
        if n['name'] in ('Video','Texture'):
            values={c['name']:c['props'][0] for c in n['children'] if c['props'] and c['name'] in ('RelativeFilename','FileName','Filename','Content')}
            if any(k in values for k in ('RelativeFilename','FileName','Filename')):images.append(values)
        for c in n['children']:walk(c)
    for tree in trees:walk(tree)
    if unsupported:raise ValueError('Animation/skin/deformer FBX is unsupported; not silently flattened')
    if len(images)>128:raise ValueError('FBX image record budget')
    return dict(version=version,globals=globals,images=images,node_count=count,declared_array_bytes=array_total,source_sha256=hashlib.sha256(raw).hexdigest())

def unit_policy(info,mode,units,up,forward):
    if mode not in ('auto','override'):raise ValueError('Import mode')
    g=info['globals'];u=g.get('UnitScaleFactor')
    if type(u) not in (int,float) or not math.isfinite(u) or u<=0:raise ValueError('FBX unit metadata missing/invalid')
    factor={'m':1.,'cm':.01,'mm':.001}[units]
    if up.lstrip('-')==forward.lstrip('-'):raise ValueError('Up and forward axes must differ')
    if mode=='auto':
        for key in ('UpAxis','UpAxisSign','FrontAxis','FrontAxisSign','CoordAxis','CoordAxisSign'):
            value=g.get(key)
            if type(value) is not int or (value not in (-1,1) if key.endswith('Sign') else value not in (0,1,2)):raise ValueError('FBX axis metadata missing/invalid')
        if len({g['UpAxis'],g['FrontAxis'],g['CoordAxis']})!=3:raise ValueError('FBX axis metadata ambiguous')
    ratio=1. if mode=='auto' else factor/(u/100.)
    if not .001<=ratio<=1000:raise ValueError('Manual FBX unit override exceeds public importer scale range')
    return dict(import_mode=mode,detected=g,global_scale=ratio,use_manual_orientation=mode=='override',axis_up=up,axis_forward=forward,post_import_unit_axis_transform=False)

def prepare_images(source,out,fbx=None,dx_ids=()):
    from PIL import Image
    source=Path(source);out=Path(out);directory=out/'textures';directory.mkdir();bindings={};rows={};pixel_total=0
    def add(name,raw,origin):
        nonlocal pixel_total
        if not name or name in ('.','..') or any(c in name for c in '/\\:\0') or len(raw)>8*1024*1024:raise ValueError('Image locator/byte budget')
        with Image.open(io.BytesIO(raw)) as image:
            if image.size!=(512,512):raise ValueError('This material profile requires source textures exactly512x512; no silent resampling')
            if image.getexif().get(274,1)!=1:raise ValueError('Texture EXIF rotation unsupported')
            image=image.convert('RGBA')
            if image.getextrema()[3]!=(255,255):raise ValueError('Only opaque textures supported')
            buf=io.BytesIO();image.save(buf,format='PNG',compress_level=6,icc_profile=None);png=buf.getvalue()
        digest=hashlib.sha256(png).hexdigest()
        if digest not in rows:
            pixel_total+=512*512
            if len(rows)>=64 or pixel_total>16*1024*1024:raise ValueError('Canonical texture budget')
            path=directory/(digest+'.png');path.write_bytes(png);rows[digest]=dict(texture_id=digest,path=str(path),content_sha256=digest,width=512,height=512,channels=4,bit_depth=8,source_sha256=hashlib.sha256(raw).hexdigest(),source_name=name,source_kind=origin)
            if digest in dx_ids or '*' in dx_ids:
                channels=image.split();flipped=Image.merge('RGBA',(channels[0],channels[1].point(lambda x:255-x),channels[2],channels[3]));preview=directory/(digest+'-preview-gl.png');flipped.save(preview,format='PNG',icc_profile=None);rows[digest]['preview_dx_path']=str(preview)
        key=name.casefold()
        if key in bindings and bindings[key]!=digest:raise ValueError('Ambiguous duplicate image filename')
        bindings[key]=digest
    for path in source.parent.iterdir():
        if path.is_file() and path.suffix.lower() in ('.png','.jpg','.jpeg'):add(path.name,path.read_bytes(),'external_uploaded')
    if fbx:
        locators=[]
        for rec in fbx['images']:
            original=rec.get('RelativeFilename') or rec.get('FileName') or rec.get('Filename');name=ntpath.basename(original.replace('/','\\'))
            if not name:raise ValueError('Empty FBX image name')
            locators.append(name)
            content=rec.get('Content')
            if content:add(name,content,'embedded')
        # Texture records can precede the Video carrying the same embedded payload.
        # Register every payload (and reject conflicts) before resolving any locator.
        for name in locators:
            if name.casefold() not in bindings:raise ValueError('Missing uploaded or embedded FBX image: '+name)
    return dict(bindings=bindings,textures=list(rows.values()),resampling='none; source512x512',JPEG_note='PNG derivative preserves decoded JPEG values; does not recover compression loss')
