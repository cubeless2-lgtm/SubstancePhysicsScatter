"""Prepare the existing five dyadic periodic bake cases. Never executes a worker."""
from pathlib import Path
import copy,hashlib,io,json,sys
from PIL import Image

def sha(raw):return hashlib.sha256(raw).hexdigest()
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8'))
def prepare(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=False);work=root/'jobs';source=work/'inputs';source.mkdir(parents=True)
    textures={}
    for name,pixel in [('constant',lambda x,y:(128,64,192,255)),('grid',lambda x,y:(x//2,y//2,((x//32)^(y//16))*8,255)),('packed',lambda x,y:(255,64,192,255)),('normal',lambda x,y:(160,96,240,255))]:
        image=Image.frombytes('RGBA',(512,512),bytes(v for y in range(512) for x in range(512) for v in pixel(x,y)));out=io.BytesIO();image.save(out,format='PNG');raw=out.getvalue();path=source/(name+'.png');path.write_bytes(raw);textures[name]=dict(texture_id=sha(raw),path=str(path),content_sha256=sha(raw),width=512,height=512,channels=4,bit_depth=8)
    vertices=[[-.25,-.25,-.125],[.25,-.25,-.125],[.25,.25,-.125],[-.25,.25,-.125],[-.25,-.25,.125],[.25,-.25,.125],[.25,.25,.125],[-.25,.25,.125]]
    faces=[([4,5,6,7],[0,0,1]),([3,2,1,0],[0,0,-1]),([0,1,5,4],[0,-1,0]),([1,2,6,5],[1,0,0]),([2,3,7,6],[0,1,0]),([3,0,4,7],[-1,0,0])]
    corners=[]
    for indices,n in faces:
        tangent=[(vertices[indices[1]][k]-vertices[indices[0]][k])/.5 for k in range(3)]
        for local in ([0,1,2],[0,2,3]):corners.append(dict(tri_id=len(corners),shape_id='TEST_ONLY_box',material_id=0,positions=[vertices[indices[i]] for i in local],uv0=[[[0,0],[1,0],[1,1],[0,1]][i] for i in local],normals=[n]*3,tangents=[tangent+[1]]*3))
    obj=source/'physics.obj';obj.write_bytes((''.join('v '+' '.join(map(str,p))+'\n' for t in corners for p in t['positions'])+''.join(f'f {i*3+1} {i*3+2} {i*3+3}\n' for i in range(12))).encode('utf-8'))
    aid,bid='a'*32,'b'*32;corner_paths={}
    for asset in (aid,bid):
        data=copy.deepcopy(corners)
        if asset==bid:
            for row in data:
                row['uv0']=[[1-u,v] for u,v in row['uv0']];row['tangents']=[[-t[0],-t[1],-t[2],-1] for t in row['tangents']]
        cp=source/(asset+'-corners.json');write(cp,dict(version=1,triangle_count=12,triangles=data));corner_paths[asset]=cp
    def binding(name,role,dx=False):
        b=dict(texture_id=textures[name]['texture_id'],channel='rgb' if role in ('base_color','normal') else 'g' if role=='roughness' else 'b',uv_set=0,wrap_u='clamp',wrap_v='clamp',filter='bilinear',color_space='sRGB' if role=='base_color' else 'linear')
        if role=='normal':b['normal_convention']='DirectX' if dx else 'OpenGL'
        return b
    def material(grid=False,normal=False,dx=False,factor=False):
        return dict(material_id=0,base_color_factor=[.25,.5,.75] if factor else [1.,1.,1.],roughness_factor=.5 if factor else 1.,metallic_factor=0. if factor else 1.,base_color_texture=None if factor else binding('grid' if grid else 'constant','base_color'),roughness_texture=None if factor else binding('packed','roughness'),metallic_texture=None if factor else binding('packed','metallic'),normal_texture=binding('normal','normal',dx) if normal else None)
    def pose(identity,asset,x,y,z,q=None):return dict(id=identity,asset_id=asset,position=[x,y,z],rotation=q or [0.,0.,0.,1.],scale=1.)
    definitions=[('x_seam',[pose(7,aid,.9375,0.,.25)],{aid:material()}),('xy_corner_grid',[pose(17,aid,.9375,.9375,.25)],{aid:material(grid=True)}),('occlusion',[pose(42,aid,.875,0.,.25),pose(7,bid,.9375,0.,.5)],{aid:material(),bid:material(factor=True)}),('rotated_handedness_DX_GL',[pose(17,aid,.9375,.9375,.5,[.5,.5,.5,.5]),pose(3,bid,-.9375,.9375,.75,[.5,.5,.5,.5])],{aid:material(grid=True,normal=True),bid:material(normal=True,dx=True)}),('empty',[],{aid:material()})]
    cases=[]
    for index,(name,poses,materials) in enumerate(definitions):
        rows=[];used=set()
        for asset,m in materials.items():
            cp=corner_paths[asset];rows.append(dict(asset_id=asset,physics_obj_sha256=sha(obj.read_bytes()),corner_data_path=str(cp),corner_data_sha256=sha(cp.read_bytes()),materials=[m]))
            used.update(b['texture_id'] for role in ('base_color','roughness','metallic','normal') if (b:=m[role+'_texture']) is not None)
        manifest=source/(name+'-material.json');write(manifest,dict(version=1,profile='material',assets=rows,textures=[t for t in textures.values() if t['texture_id'] in used]))
        expanded=[]
        for p in poses:
            for image,(kx,ky) in enumerate(( (x,y) for x in (-1,0,1) for y in (-1,0,1) )):
                image_pose=copy.deepcopy(p);image_pose['id']=p['id']*9+image;image_pose['position'][0]+=kx*2;image_pose['position'][1]+=ky*2;expanded.append(image_pose)
        paths=[]
        for variant,data in enumerate((poses,expanded)):
            identity=f'{index*2+variant+1:032x}';run=work/'runs'/identity
            request=dict(job_id=identity,assets=[dict(asset_id=asset,path=str(obj),content_hash=sha(obj.read_bytes()),format='obj',scale=1.,weight=1.) for asset in materials],simulation=dict(count=max(1,len(data)),seed=1,width=2.,depth=2.,seconds=1.,edges='periodic' if variant==0 else 'walls'),bake=dict(resolution=64,samples=1,height_min=0.,height_max=1.,normal='OpenGL' if index==3 else 'DirectX'),output_directory=str(run),review_v1=dict(version=1,manifest_path=str(manifest),manifest_sha256=sha(manifest.read_bytes()),export_hulls=False,bake_pbr=True))
            rp=root/(name+('-periodic' if variant==0 else '-expanded')+'.json');write(rp,request);paths.append(str(rp))
        cases.append(dict(id=name,poses=poses,expanded_poses=expanded,periodic_request=paths[0],expanded_request=paths[1]))
    spec=root/'fixtures.json';write(spec,dict(TEST_ONLY=True,cases=cases))
    pins={str(p):sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()};write(root/'inputs.json',dict(TEST_ONLY=True,physics_observation=False,fixture_cases=5,bake_calls=10,expected_pixel_tolerance=0,timeout_seconds=90,log_limit=8*1024*1024,artifact_limit=64*1024*1024,pins=pins,analytic=dict(x_seam_covered=256,x_seam_height_code=24576,x_seam_BC=[128,64,192],x_seam_R=64,x_seam_M=192,empty_H=0,empty_C=0,empty_BC=[0,0,0],empty_R=255,empty_M=0,empty_N=[128,128,255])))
    return dict(spec=str(spec),cases=5,bake_calls=10,input_files=len(pins),pixel_tolerance=0)

if __name__=='__main__':print(json.dumps(prepare(sys.argv[1])))
