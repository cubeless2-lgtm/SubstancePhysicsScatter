"""Apply an immutable locally staged viewer result to a Designer scatter graph.

All graph operations run on Designer's UI thread.  The caller must fetch a
job-pinned manifest, verify it again after downloading, and lock the panel.
"""
from pathlib import Path
import hashlib, math, os, re, stat, struct
from .errors import HOST_ERRORS, rollback_or_raise

HNC=('height','normal','coverage')
PBR=('basecolor','roughness','metallic','normal_material')
HEX=re.compile(r'^[0-9a-f]{64}$')
JOB=re.compile(r'^[0-9a-f]{32}$')

def owned_stage(graph,job,host):
    """Reject links and Windows reparse points under the SBS directory."""
    from .handoff_paths import owned_external
    return owned_external(graph.getPackage().getFilePath(),graph.getIdentifier(),job,host.result_directory(graph))

def connection_snapshot(graph,host):
    rows=[]
    for output in graph.getOutputNodes():
        name=output.getAnnotationPropertyValueFromId('identifier').get()
        links=host.incoming_sources(graph,output.getIdentifier(),'inputNodeOutput')
        rows.append((name,output.getIdentifier(),tuple((node.getIdentifier(),prop.getId()) for node,prop in links)))
    if len({x[0] for x in rows})!=len(rows):raise ValueError('Duplicate output identifier')
    return tuple(sorted(rows))

def verify_files(graph,manifest,files,host):
    if type(manifest) is not dict or manifest.get('schema_version')!=1 or not JOB.fullmatch(str(manifest.get('job_id',''))):raise ValueError('Invalid viewer manifest')
    maps=manifest.get('maps')
    if type(maps) is not dict or set(maps) not in (set(HNC),set(HNC+PBR)) or set(files)!=set(maps):raise ValueError('Expected one complete HNC or HNC/PBR bundle')
    root=owned_stage(graph,manifest['job_id'],host)
    sizes=set()
    for role,row in maps.items():
        if type(row) is not dict or not HEX.fullmatch(str(row.get('sha256',''))) or type(row.get('bytes')) is not int or not 0<row['bytes']<=32*1024*1024:raise ValueError('Invalid map descriptor: '+role)
        p=Path(files[role]);expected=root/(role+'.png')
        if p.is_symlink() or p.resolve()!=expected.resolve() or p.name!=role+'.png' or not p.is_file():raise ValueError('Map outside owned staged bundle: '+role)
        info=p.lstat()
        if stat.S_ISLNK(info.st_mode) or os.name=='nt' and (not hasattr(info,'st_file_attributes') or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT):raise ValueError('Staged map is a link or reparse point')
        if p.stat().st_size!=row['bytes']:raise ValueError('Staged map length changed: '+role)
        raw=p.read_bytes()
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256'] or raw[:8]!=b'\x89PNG\r\n\x1a\n' or len(raw)<33 or raw[12:16]!=b'IHDR':raise ValueError('Staged map changed: '+role)
        width,height,bits,color=struct.unpack('>IIBB',raw[16:26]);sizes.add((width,height))
        types={0:'GREY',2:'RGB',4:'GREY_ALPHA',6:'RGBA'}
        if (width,height,bits,types.get(color))!=(row.get('width'),row.get('height'),row.get('bit_depth'),row.get('color_type')) or row.get('format')!='PNG':raise ValueError('Map image descriptor differs: '+role)
        if row.get('color_space')!=('sRGB' if role=='basecolor' else 'linear'):raise ValueError('Map color space differs: '+role)
        if role in ('normal','normal_material') and (row.get('normal_convention') not in ('DirectX','OpenGL') or row.get('normal_space')!='object/canonical XYZ'):raise ValueError('Map normal semantics differ: '+role)
    if len(sizes)!=1:raise ValueError('Map resolutions differ')
    width,height=next(iter(sizes))
    if width!=height or not 16<=width<=2048 or width&(width-1):raise ValueError('Designer requires square power-of-two maps')
    return root,width

def apply_external(graph,manifest,files,*,guard=lambda:None,connection_guard=lambda:None,_host=None):
    """Return rollback callable. Existing Designer current metadata is untouched."""
    if _host is None:
        from . import designer as host
    else:host=_host
    from sd.api.sdresourcebitmap import SDResourceBitmap
    from sd.api.sdresource import EmbedMethod
    from sd.api.sdproperty import SDPropertyCategory, SDPropertyInheritanceMethod
    from sd.api.sdvaluestring import SDValueString
    from sd.api.sdvalueint2 import SDValueInt2
    from sd.api.sdvalueenum import SDValueEnum
    from sd.api.sdbasetypes import float2,int2
    import uuid
    root,res=verify_files(graph,manifest,files,host);guard();connection_guard()
    old_state=host.settings(graph) or {};outputs={}
    for output in graph.getOutputNodes():
        name=output.getAnnotationPropertyValueFromId('identifier').get()
        if name in outputs:raise ValueError('Duplicate output identifier')
        outputs[name]=output
    if not set(HNC)<=set(outputs):raise ValueError('Scatter HNC outputs missing')
    old_external=old_state.get('external_current') or {};owned=set(old_external.get('channels',[]))
    if set(PBR)&set(outputs)-owned:raise ValueError('PBR output identifier belongs to an existing graph output')
    if set(manifest['maps'])==set(HNC) and set(PBR)&set(outputs):raise ValueError('This graph has PBR outputs; apply a complete seven-channel result')
    staged=[];created=[];previous=[];old_properties=[];package=graph.getPackage()
    def rollback():
        for output,prop,connections in reversed(previous):
            output.deletePropertyConnections(prop)
            for node,source in connections:node.newPropertyConnectionFromId(source,output,'inputNodeOutput')
        for owner,prop,value,inheritance in reversed(old_properties):
            owner.setPropertyValue(prop,value);owner.setPropertyInheritanceMethod(prop,inheritance)
        for node,resource in reversed(staged):graph.deleteNode(node);resource.delete()
        for output in reversed(created):graph.deleteNode(output)
        host.store(graph,old_state);host.compute_graph(graph)
    def configure(owner,name,value):
        prop=owner.getPropertyFromId(name,SDPropertyCategory.Input)
        if prop is None:return
        old_properties.append((owner,prop,owner.getPropertyValue(prop),owner.getPropertyInheritanceMethod(prop)))
        owner.setPropertyInheritanceMethod(prop,SDPropertyInheritanceMethod.Absolute);owner.setPropertyValue(prop,value)
    try:
        size=SDValueInt2.sNew(int2(int(math.log2(res)),int(math.log2(res))))
        configure(graph,'$outputsize',size);configure(graph,'$format',SDValueEnum.sFromValueId('sbs::compositing::format','16_bits_per_channel'))
        for i,role in enumerate(manifest['maps']):
            if role not in outputs:
                node=graph.newNode('sbs::compositing::output');created.append(node)
                node.setAnnotationPropertyValueFromId('identifier',SDValueString.sNew(role));node.setAnnotationPropertyValueFromId('label',SDValueString.sNew(role.replace('_',' ').title()));node.setPosition(float2(400,i*160));outputs[role]=node
            resource=SDResourceBitmap.sNewFromFile(package,str(files[role]),EmbedMethod.Linked)
            try:
                resource.setIdentifier('scatter_bitmap_'+uuid.uuid4().hex);node=graph.newInstanceNode(resource)
            except HOST_ERRORS:
                resource.delete();raise
            staged.append((node,resource));node.setPosition(float2(0,i*160))
            fmt='16_bits_per_channel' if role=='height' else '8_bits_per_channel'
            for owner in (node,outputs[role]):configure(owner,'$outputsize',size);configure(owner,'$format',SDValueEnum.sFromValueId('sbs::compositing::format',fmt))
        verify_files(graph,manifest,files,host);guard()
        for role,(node,resource) in zip(manifest['maps'],staged):
            output=outputs[role];prop=output.getPropertyFromId('inputNodeOutput',SDPropertyCategory.Input)
            previous.append((output,prop,[(src,p.getId()) for src,p in host.incoming_sources(graph,output.getIdentifier(),'inputNodeOutput')]))
            output.deletePropertyConnections(prop);node.newPropertyConnectionFromId(node.getProperties(SDPropertyCategory.Output)[0].getId(),output,'inputNodeOutput')
        host.compute_graph(graph);verify_files(graph,manifest,files,host);guard()
        state=dict(old_state);state['external_current']={'job_id':manifest['job_id'],'channels':list(manifest['maps']),'manifest':manifest,'directory':str(root)};host.store(graph,state)
    except HOST_ERRORS as error:rollback_or_raise(error,rollback)
    return rollback
