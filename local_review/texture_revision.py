"""Canonical UV0 binding revisions: append preview pixels, preserve geometry bytes."""
import copy,io,json,re,struct
from PIL import Image,ImageOps
import material_revision as m,pbr_contract as pbr
ROLES=('base_color','roughness','metallic','normal')
FIELDS=('texture_id','path','content_sha256','width','height','channels','bit_depth')

def library(old,manifest):
    result={}
    for row in [*manifest['textures'],*old.get('material_texture_library',[]),*old.get('manual_textures',[])]:
        clean={k:row[k] for k in FIELDS};tid=pbr.hexsha(clean['texture_id'])
        if tid!=clean['content_sha256']:raise ValueError('Canonical texture SHA identity')
        for field,value in (('width',512),('height',512),('channels',4),('bit_depth',8)):pbr.whole(clean[field],value,value)
        if type(clean['path']) is not str:raise ValueError('Texture locator type')
        if tid in result and {k:v for k,v in result[tid].items() if k!='path'}!={k:v for k,v in clean.items() if k!='path'}:raise ValueError('Texture identity conflict')
        result.setdefault(tid,clean)
    if len(result)>64:raise ValueError('Material texture library limit64')
    return result

def upload_format(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('PNG','JPEG') or image.size!=(512,512):raise ValueError('Manual texture requires actual PNG/JPG512')
        if image.format=='PNG' and (raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[24]!=8):raise ValueError('Manual PBR texture requires8-bit PNG')

def rgba(raw):
    parsed=pbr.png(raw)
    if parsed['width']!=512 or parsed['height']!=512 or parsed['header'][2:4]!=(8,6):raise ValueError('Canonical texture must be512 RGBA8')
    with Image.open(io.BytesIO(raw)) as image:
        out=image.convert('RGBA');out.load()
    if out.getextrema()[3]!=(255,255):raise ValueError('Only opaque canonical textures supported')
    return out

def png(image):
    out=io.BytesIO();image.save(out,format='PNG',icc_profile=None);return out.getvalue()

def channel_preview(raw,channel):
    if channel not in ('rgb','r','g','b'):raise ValueError('Texture preview channel')
    image=rgba(raw)
    if channel!='rgb':
        c=image.getchannel({'r':'R','g':'G','b':'B'}[channel]);image=Image.merge('RGBA',(c,c,c,Image.new('L',image.size,255)))
    return png(image)

def bindings(records,edits,source,available):
    updated=copy.deepcopy(records);by={str(row['material_id']):row for row in updated}
    if type(edits) is not dict or not 1<=len(edits)<=64:raise ValueError('Binding edits1..64 slots')
    for key,roles in edits.items():
        if key not in by or type(roles) is not dict or not roles or set(roles)-set(ROLES):raise ValueError('Binding slot/role')
        for role,value in roles.items():
            if type(value) is not dict or value.get('mode') not in ('auto','none','texture'):raise ValueError('Binding mode')
            mode=value['mode']
            if mode in ('auto','none'):
                if set(value)!={'mode'}:raise ValueError('Auto/None binding accepts mode only')
                by[key][role+'_texture']=copy.deepcopy(source[key][role+'_texture']) if mode=='auto' else None
                continue
            if set(value)-{'mode','texture_id','channel','color_space','wrap','normal_convention'}:raise ValueError('Unknown binding field')
            tid=value.get('texture_id')
            if tid not in available:raise ValueError('Texture is not in this asset library')
            channel=value.get('channel','rgb' if role in ('base_color','normal') else 'r');space=value.get('color_space','sRGB' if role=='base_color' else 'linear');wrap=value.get('wrap','repeat')
            if channel not in (('rgb',) if role in ('base_color','normal') else ('r','g','b')) or space not in (('sRGB','linear') if role=='base_color' else ('linear',)) or wrap not in ('repeat','clamp'):raise ValueError('Binding channel/color space/wrap')
            row=dict(texture_id=tid,channel=channel,uv_set=0,wrap_u=wrap,wrap_v=wrap,filter='bilinear',color_space=space)
            if role=='normal':
                convention=value.get('normal_convention','OpenGL')
                if convention not in ('OpenGL','DirectX'):raise ValueError('Normal convention')
                row['normal_convention']=convention
            elif 'normal_convention' in value:raise ValueError('Normal convention on non-normal role')
            by[key][role+'_texture']=row
    return updated

def edit_glb(raw,records,edits,source,available,read):
    doc,chunks=m.split_glb(raw)
    if len(chunks)!=2 or chunks[1][0]!=0x004e4942 or len(doc.get('buffers',[]))!=1:raise ValueError('Binding revisions require canonical embedded single BIN')
    binary=bytearray(chunks[1][1]);old_binary=bytes(binary);before=copy.deepcopy(doc)
    if not 0<=len(binary)-doc['buffers'][0]['byteLength']<=3:raise ValueError('GLB buffer length')
    updated=bindings(records,edits,source,available);by={str(row['material_id']):row for row in updated};mapped={}
    for i,mat in enumerate(doc['materials']):
        match=re.fullmatch('ReviewMat_(0|[1-9][0-9]?)',mat.get('name',''))
        if match is None or match[1] not in by or match[1] in mapped:raise ValueError('Canonical material owner mapping')
        mapped[match[1]]=i
    if set(edits)-set(mapped):raise ValueError('Edited slot has no exported GLB material')
    images={}
    def image(binding):
        tid=binding['texture_id']
        if tid not in images:
            t=available[tid];images[tid]=rgba(read(t['path'],t['content_sha256'],8*1024*1024))
        return images[tid]
    def add_texture(data,binding,name):
        if len(data)>8*1024*1024:raise ValueError('Preview PNG budget')
        if len(binary)+len(data)+3>m.GLB_LIMIT:raise ValueError('Preview BIN budget')
        binary.extend(b'\0'*((-len(binary))%4));offset=len(binary);binary.extend(data)
        views=doc.setdefault('bufferViews',[]);vi=len(views);views.append(dict(buffer=0,byteOffset=offset,byteLength=len(data)))
        ims=doc.setdefault('images',[]);ii=len(ims);ims.append(dict(bufferView=vi,mimeType='image/png',name=name))
        samplers=doc.setdefault('samplers',[]);si=len(samplers);samplers.append(dict(magFilter=9729,minFilter=9729,wrapS=10497 if binding['wrap_u']=='repeat' else 33071,wrapT=10497 if binding['wrap_v']=='repeat' else 33071))
        textures=doc.setdefault('textures',[]);ti=len(textures);textures.append(dict(source=ii,sampler=si,name=name))
        if len(views)>4096 or len(ims)>1024 or len(textures)>1024 or len(samplers)>1024:raise ValueError('GLB appended texture budget')
        return dict(index=ti,texCoord=0)
    for key in edits:
        slot=mapped[key];row=by[key];mat=doc['materials'][slot];mr=mat.setdefault('pbrMetallicRoughness',{})
        primitives=[p for mesh in doc['meshes'] for p in mesh['primitives'] if p.get('material')==slot]
        if not primitives or any('TEXCOORD_0' not in p['attributes'] for p in primitives):raise ValueError('Binding requires existing canonical UV0')
        bc,r,metal,n=(row[role+'_texture'] for role in ROLES)
        if n and any(not {'POSITION','NORMAL','TEXCOORD_0','TANGENT'}<=set(p['attributes']) for p in primitives):raise ValueError('Normal binding requires existing POSITION/NORMAL/UV0/TANGENT; no fabricated tangents')
        if bc:mr['baseColorTexture']=add_texture(png(image(bc)),bc,f'Role_{key}_base_color')
        else:mr.pop('baseColorTexture',None)
        if r or metal:
            sampler=r or metal
            if r and metal and (r['wrap_u'],r['wrap_v'])!=(metal['wrap_u'],metal['wrap_v']):raise ValueError('glTF packed Roughness/Metallic preview requires the same UV wrap')
            scalar=lambda binding:image(binding).getchannel({'r':'R','g':'G','b':'B'}[binding['channel']]) if binding else Image.new('L',(512,512),255)
            packed=Image.merge('RGBA',(Image.new('L',(512,512),255),scalar(r),scalar(metal),Image.new('L',(512,512),255)))
            mr['metallicRoughnessTexture']=add_texture(png(packed),sampler,f'Role_{key}_roughness_metallic')
        else:mr.pop('metallicRoughnessTexture',None)
        if n:
            normal=image(n)
            if n['normal_convention']=='DirectX':
                channels=normal.split();normal=Image.merge('RGBA',(channels[0],ImageOps.invert(channels[1]),channels[2],channels[3]))
            mat['normalTexture']=dict(**add_texture(png(normal),n,f'Role_{key}_normal_gl'),scale=1.)
        else:mat.pop('normalTexture',None)
        mr.update(baseColorFactor=[*row['base_color_factor'],1.],roughnessFactor=row['roughness_factor'],metallicFactor=row['metallic_factor'])
        mat.setdefault('extras',{})['review_texture_preview']=dict(version=1,base_color_space=bc['color_space'] if bc else None)
    length=len(binary);doc['buffers'][0]['byteLength']=length;binary.extend(b'\0'*((-length)%4));json_raw=json.dumps(doc,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode();json_raw+=b' '*((-len(json_raw))%4)
    size=28+len(json_raw)+len(binary)
    if size>m.GLB_LIMIT:raise ValueError('Revised GLB budget')
    output=struct.pack('<III',0x46546c67,2,size)+struct.pack('<II',len(json_raw),0x4e4f534a)+json_raw+struct.pack('<II',len(binary),0x004e4942)+binary
    check,parts=m.split_glb(output)
    if parts[1][1][:len(old_binary)]!=old_binary:raise ValueError('Original BIN prefix changed')
    # Exact undo checks admit only appended texture arrays, buffer length and
    # the edited materials; mesh/accessor/UV and all unrelated JSON stay strict.
    restored=copy.deepcopy(check)
    for field in ('bufferViews','images','textures','samplers'):
        if field in before:
            if restored[field][:len(before[field])]!=before[field]:raise ValueError('Existing texture/geometry array changed')
            restored[field]=before[field]
        else:restored.pop(field,None)
    restored['buffers']=before['buffers']
    for key in edits:restored['materials'][mapped[key]]=before['materials'][mapped[key]]
    if restored!=before:raise ValueError('GLB JSON changed outside binding revision')
    return output,updated
