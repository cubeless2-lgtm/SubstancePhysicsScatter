"""Blender5.2 private OBJ/FBX canonical derivatives; source files are never saved."""
import sys,json,math,hashlib,struct,ntpath
from pathlib import Path
from array import array
import bpy
from mathutils import Matrix
from bpy_extras.node_shader_utils import PrincipledBSDFWrapper

def f32(v):
    if not math.isfinite(float(v)):raise ValueError('Nonfinite canonical value')
    return struct.unpack('f',struct.pack('f',float(v)))[0]
def vec(v):return [f32(x) for x in v]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def import_source(s):
    if s['format']=='obj':
        bpy.ops.wm.obj_import(filepath=s['source'],forward_axis='Y',up_axis='Z')
        return Matrix.Scale({'m':1.,'cm':.01,'mm':.001}[s['units']],4)@(Matrix.Identity(4) if s['up_axis']=='Z' else Matrix.Rotation(math.pi/2,4,'X'))
    from io_scene_fbx.fbx_utils import RIGHT_HAND_AXES
    p=s['fbx_policy'];g=p['detected'];key=((g.get('UpAxis'),g.get('UpAxisSign')),(g.get('FrontAxis'),g.get('FrontAxisSign')),(g.get('CoordAxis'),g.get('CoordAxisSign')))
    if not p['use_manual_orientation'] and key not in RIGHT_HAND_AXES.values():raise ValueError('FBX axis mapping unsupported; no fallback')
    from bpy_extras import image_utils
    original=image_utils.load_image;registry=s['image_registry'];images={t['texture_id']:t for t in registry['textures']}
    def safe_image(filepath,*args,**kwargs):
        name=ntpath.basename(str(filepath).replace('/','\\')).casefold();tid=registry['bindings'].get(name)
        if tid not in images:raise ValueError('FBX image outside owned uploaded/embedded registry')
        path=Path(images[tid]['path']);kwargs.update(dirname=str(path.parent),recursive=False,place_holder=False)
        image=original(str(path),**kwargs)
        if image is None:raise ValueError('Owned image load failed')
        # Do not mistake lazy image.has_data before FBX packing for a failed embedded image.
        return image
    image_utils.load_image=safe_image
    try:
        bpy.context.scene.unit_settings.system='NONE'
        bpy.ops.import_scene.fbx(filepath=s['source'],use_manual_orientation=p['use_manual_orientation'],global_scale=p['global_scale'],axis_up=p['axis_up'],axis_forward=p['axis_forward'],use_image_search=False,use_anim=False,bake_space_transform=False,use_custom_normals=True)
    finally:image_utils.load_image=original
    return Matrix.Identity(4)

def auto_texture(socket,role):
    if not socket.is_linked:return None
    if len(socket.links)!=1:raise ValueError('Ambiguous material links')
    link=socket.links[0];node=link.from_node;channel='rgb'
    if node.bl_idname in ('ShaderNodeSeparateColor','ShaderNodeSeparateRGB'):
        channel={'Red':'r','Green':'g','Blue':'b','R':'r','G':'g','B':'b'}.get(link.from_socket.name)
        if channel is None or not node.inputs[0].is_linked:raise ValueError('Packed input unsupported')
        node=node.inputs[0].links[0].from_node
    elif node.bl_idname=='ShaderNodeNormalMap':
        strength=node.inputs['Strength'];color=node.inputs['Color']
        if role!='normal' or node.space!='TANGENT' or strength.is_linked:raise ValueError('Normal space/strength unsupported')
        if strength.default_value==0 or not color.is_linked and tuple(color.default_value)==(.5,.5,1.,1.):return None
        if strength.default_value!=1 or not color.is_linked:raise ValueError('Normal space/strength unsupported')
        node=color.links[0].from_node
    if node.bl_idname!='ShaderNodeTexImage' or node.image is None:raise ValueError('Procedural input unsupported; assign manually')
    if node.projection!='FLAT' or node.extension not in ('REPEAT','EXTEND'):raise ValueError('Projection/wrap unsupported')
    if node.inputs['Vector'].is_linked:
        link=node.inputs['Vector'].links[0]
        if link.from_node.bl_idname!='ShaderNodeTexCoord' or link.from_socket.name!='UV':raise ValueError('Only unmapped UV0 supported')
    if role in ('roughness','metallic') and channel=='rgb':
        pixels=node.image.pixels;data=array('f',[0])*len(pixels);pixels.foreach_get(data)
        if any(data[i]!=data[i+1] or data[i]!=data[i+2] for i in range(0,len(data),4)):raise ValueError('Choose scalar packed channel explicitly')
        channel='r'
    return dict(image=node.image,channel=channel,wrap='repeat' if node.extension=='REPEAT' else 'clamp')

def make_materials(s,objects):
    registry=s['image_registry'];textures={t['texture_id']:t for t in registry['textures']};old=[]
    for o in objects:
        for m in o.data.materials:
            if m is not None and m not in old:old.append(m)
    if not old:old=[None]
    if len(old)>64:raise ValueError('Material limit64')
    records=[];preview=[];ui=[];warnings=[]
    for mid,material in enumerate(old):
        wrap=PrincipledBSDFWrapper(material,is_readonly=True) if material else None;bsdf=wrap.node_principled_bsdf if wrap else None
        if bsdf and (bsdf.inputs['Alpha'].is_linked or bsdf.inputs['Alpha'].default_value!=1):raise ValueError('Only opaque source materials supported')
        row=dict(material_id=mid,base_color_factor=vec(bsdf.inputs['Base Color'].default_value[:3]) if bsdf else [.8]*3,roughness_factor=f32(bsdf.inputs['Roughness'].default_value) if bsdf else .5,metallic_factor=f32(bsdf.inputs['Metallic'].default_value) if bsdf else 0.,base_color_texture=None,roughness_texture=None,metallic_texture=None,normal_texture=None)
        new=bpy.data.materials.new('ReviewMat_'+str(mid));new.use_nodes=True;tree=new.node_tree;tree.nodes.clear();p=tree.nodes.new('ShaderNodeBsdfPrincipled');out=tree.nodes.new('ShaderNodeOutputMaterial');tree.links.new(p.outputs['BSDF'],out.inputs['Surface'])
        info=dict(material_id=mid,name=material.name if material else 'Unassigned',roles={},warnings=[])
        if material is not None and bsdf is None:info['warnings'].append('Source shader is not supported Principled BSDF; material profile unavailable')
        for role,label in (('base_color','Base Color'),('roughness','Roughness'),('metallic','Metallic'),('normal','Normal')):
            setting=s.get('material_overrides',{}).get(str(mid),{}).get(role,{'mode':'auto'});auto=None;error=None
            if setting['mode']=='auto' and bsdf:
                try:auto=auto_texture(bsdf.inputs[label],role)
                except ValueError as e:error=str(e)
            tid=setting.get('texture_id') if setting['mode']=='texture' else None
            if auto:
                path=Path(bpy.path.abspath(auto['image'].filepath));name=ntpath.basename(str(path).replace('/','\\')).casefold();tid=registry['bindings'].get(name)
                if tid is None and path.stem in textures:tid=path.stem
                if tid is None:error='Image not found in owned registry'
            if setting['mode']=='none':tid=None;error=None
            channel=setting.get('channel',auto['channel'] if auto else 'rgb' if role in ('base_color','normal') else 'r');space=setting.get('color_space','sRGB' if role=='base_color' else 'linear');extension=setting.get('wrap',auto['wrap'] if auto else 'repeat');convention=setting.get('normal_convention','OpenGL')
            if role!='base_color' and space!='linear':raise ValueError('Data roles must be linear/Non-Color')
            if channel not in (('rgb',) if role in ('base_color','normal') else ('r','g','b')) or extension not in ('repeat','clamp') or space not in ('sRGB','linear') or convention not in ('OpenGL','DirectX'):raise ValueError('Material binding fields')
            if error:info['warnings'].append(role+': '+error)
            if tid:
                if tid not in textures:raise ValueError('Manual texture ID missing')
                b=dict(texture_id=tid,channel=channel,uv_set=0,wrap_u=extension,wrap_v=extension,filter='bilinear',color_space=space)
                if role=='normal':b['normal_convention']=convention
                row[role+'_texture']=b;image_path=textures[tid].get('preview_dx_path') if role=='normal' and convention=='DirectX' else textures[tid]['path']
                if not image_path:raise ValueError('DX preview copy not prepared')
                image=bpy.data.images.load(image_path,check_existing=False);image.name=f'Role_{mid}_{role}';image.colorspace_settings.name='sRGB' if space=='sRGB' else 'Non-Color'
                tex=tree.nodes.new('ShaderNodeTexImage');tex.image=image;tex.extension='REPEAT' if extension=='repeat' else 'EXTEND';output=tex.outputs['Color']
                if channel!='rgb':
                    separate=tree.nodes.new('ShaderNodeSeparateColor');separate.mode='RGB';tree.links.new(output,separate.inputs[0]);output=separate.outputs[{'r':'Red','g':'Green','b':'Blue'}[channel]]
                if role=='normal':
                    normal=tree.nodes.new('ShaderNodeNormalMap');tree.links.new(output,normal.inputs['Color']);output=normal.outputs['Normal']
                else:row[role+'_factor']=[1.,1.,1.] if role=='base_color' else 1.
                tree.links.new(output,p.inputs[label])
            info['roles'][role]=dict(mode=setting['mode'],binding=row[role+'_texture'],status='unsupported' if error else 'manual' if setting['mode']!='auto' else 'texture' if tid else 'geometric_fallback' if role=='normal' else 'constant')
        p.inputs['Base Color'].default_value=(*row['base_color_factor'],1);p.inputs['Roughness'].default_value=row['roughness_factor'];p.inputs['Metallic'].default_value=row['metallic_factor']
        if any(not 0<=n<=1 for n in (*row['base_color_factor'],row['roughness_factor'],row['metallic_factor'])):raise ValueError('Material factor range')
        records.append(row);preview.append(new);ui.append(info);warnings.extend(info['warnings'])
    return old,records,preview,ui,warnings

def corners(obj,matrix,shape,material_ids):
    mesh=obj.data;mesh.calc_loop_triangles();uv=mesh.uv_layers.active;ready=uv is not None;reason=None
    if uv:
        try:mesh.calc_tangents(uvmap=uv.name)
        except RuntimeError:ready=False;reason='Degenerate UV tangent basis'
    else:reason='UV0 missing: geometry/Hull only'
    det=matrix.to_3x3().determinant()
    if abs(det)<1e-12:raise ValueError('Singular source transform')
    normal_matrix=matrix.to_3x3().inverted().transposed();rows=[]
    for tri in mesh.loop_triangles:
        loops=list(tri.loops);loops=loops if det>0 else [loops[0],loops[2],loops[1]];positions=[];normals=[];uvs=[];tangents=[]
        for li in loops:
            loop=mesh.loops[li];n=(normal_matrix@mesh.corner_normals[li].vector).normalized();positions.append(vec(matrix@mesh.vertices[loop.vertex_index].co));normals.append(vec(n));uvs.append(vec(uv.data[li].uv) if uv else None)
            if ready:
                t=matrix.to_3x3()@loop.tangent;t=(t-n*t.dot(n)).normalized();w=loop.bitangent_sign*(1 if det>0 else -1)
                if t.length_squared==0 or w not in (-1.,1.):ready=False;reason='Invalid tangent basis'
                tangents.append([*vec(t),float(w)])
            else:tangents.append(None)
        if len({t[3] for t in tangents if t})>1:ready=False;reason='Mixed tangent signs in one triangle'
        material=mesh.materials[tri.material_index] if len(mesh.materials)>tri.material_index else None
        rows.append(dict(tri_id=0,shape_id=shape,material_id=material_ids.get(material,0),positions=positions,uv0=uvs,normals=normals,tangents=tangents))
    return rows,ready,reason

def save_asset(s,out,rows,materials,records,ui,hierarchy,parts,ready,warnings):
    if not 1<=len(rows)<5000:raise ValueError('Canonical asset requires1..4999 triangles')
    positions=[];normals=[]
    for i,t in enumerate(rows):t['tri_id']=i;positions.extend(t['positions']);normals.extend(t['normals'])
    mesh=bpy.data.meshes.new('CanonicalMesh');mesh.from_pydata(positions,[],[(3*i,3*i+1,3*i+2) for i in range(len(rows))]);mesh.update()
    for m in materials:mesh.materials.append(m)
    for i,p in enumerate(mesh.polygons):p.material_index=rows[i]['material_id']
    mesh.normals_split_custom_set_from_vertices(normals)
    if all(all(x is not None for x in t['uv0']) for t in rows):
        layer=mesh.uv_layers.new(name='UVMap')
        for i,t in enumerate(rows):
            for k in range(3):layer.data[3*i+k].uv=t['uv0'][k]
    obj=bpy.data.objects.new('CanonicalAsset',mesh);bpy.context.collection.objects.link(obj);bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    with (out/'physics.obj').open('x',encoding='utf8',newline='\n') as file:
        file.write('# Canonical RH_Z_UP meters; same corner geometry as scene.glb\n')
        for p in positions:file.write('v '+' '.join(format(x,'.9g') for x in p)+'\n')
        for i in range(len(rows)):file.write(f'f {3*i+1} {3*i+2} {3*i+3}\n')
    bpy.ops.export_scene.gltf(filepath=str(out/'scene.glb'),export_format='GLB',use_selection=True,export_yup=True,export_apply=True,export_materials='EXPORT',export_texcoords=True,export_normals=True,export_tangents=ready)
    (out/'corners.json').write_text(json.dumps(dict(version=1,triangle_count=len(rows),triangles=rows),allow_nan=False),encoding='utf8')
    meta=dict(schema_version=2,importer='Blender '+bpy.app.version_string,source_name=Path(s['source']).name,source_sha256=sha(s['source']),units=s['units'],source_up_axis=s['up_axis'],import_mode=s['import_mode'],fbx_policy=s.get('fbx_policy'),canonical_coordinate_system='RH_Z_UP',canonical_units='meters',vertices=len(positions),triangles=len(rows),bounds=dict(min=[min(p[k] for p in positions) for k in range(3)],max=[max(p[k] for p in positions) for k in range(3)]),parts_mode=s['parts_mode'],part_info=parts,hierarchy=hierarchy,materials=ui,material_records=records,uv_layers=['UVMap'] if ready else [],material_ready=ready and not warnings,warnings=warnings,normal_fallback='geometric when no normal texture; not a fabricated normal map',geometry_only_physics=True,files={n:sha(out/n) for n in ('physics.obj','scene.glb','corners.json')})
    (out/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');bpy.data.objects.remove(obj,do_unlink=True)

def main():
    s=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf8'));source=Path(s['source']).resolve();out=Path(s['output']).resolve()
    if source.suffix.lower() not in ('.obj','.fbx') or not source.is_relative_to(out.parent):raise ValueError('Owned source required')
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False);axis=import_source(s);objects=sorted([o for o in bpy.context.scene.objects if o.type=='MESH'],key=lambda o:o.name_full)
    if not objects or len(objects)>128 or any(o.modifiers or o.animation_data for o in objects):raise ValueError('Mesh part/animation/modifier profile unsupported')
    hierarchy=[dict(name=o.name_full,parent=o.parent.name_full if o.parent else None,type=o.type,local_matrix=[list(r) for r in o.matrix_local],world_matrix=[list(r) for r in o.matrix_world]) for o in bpy.context.scene.objects]
    old,records,preview,ui,warnings=make_materials(s,objects);ids={m:i for i,m in enumerate(old)};all_rows=[];all_ready=True;parts=[]
    for i,obj in enumerate(objects):
        matrix=axis@obj.matrix_world;rows,ready,reason=corners(obj,matrix,'part_'+str(i),ids);all_ready&=ready
        if reason:warnings.append(obj.name+': '+reason)
        part=dict(shape_id='part_'+str(i),name=obj.name_full,parent=obj.parent.name_full if obj.parent else None,world_matrix=[list(r) for r in matrix]);parts.append(part)
        if s['parts_mode']=='split':
            target=out/('part_'+str(i));target.mkdir();pivot=vec(matrix.translation)
            for t in rows:t['positions']=[[f32(p[k]-pivot[k]) for k in range(3)] for p in t['positions']]
            save_asset(s,target,rows,preview,records,ui,hierarchy,dict(parts=[part],canonical_pivot=pivot),ready,warnings[:])
        else:all_rows.extend(rows)
    if s['parts_mode']=='group':save_asset(s,out,all_rows,preview,records,ui,hierarchy,dict(parts=parts,canonical_pivot=[0,0,0]),all_ready,warnings)
    (out/'index.json').write_text(json.dumps(dict(parts=[str(p.relative_to(out)) for p in sorted(out.glob('part_*/metadata.json'))] if s['parts_mode']=='split' else ['metadata.json'])),encoding='utf8')
if __name__=='__main__':
    try:main()
    except BaseException:
        import traceback
        traceback.print_exc();sys.exit(1)
