"""Exact physics OBJ↔corner identity. No triangulation or geometry correction here."""
import json,math,struct
def number(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('Finite non-bool canonical value')
    return v
def f32(v):return struct.unpack('f',struct.pack('f',number(v)))[0]
def validate(obj_raw,corner_raw,materials,require_material):
    if len(obj_raw)>8*1024*1024 or len(corner_raw)>8*1024*1024:raise ValueError('Canonical file byte budget')
    vertices=[];faces=[]
    for line in obj_raw.decode('utf8').splitlines():
        values=line.split()
        if not values or values[0].startswith('#'):continue
        if values[0]=='v' and len(values)==4:vertices.append([f32(float(v)) for v in values[1:]])
        elif values[0]=='f' and len(values)==4:faces.append([int(v)-1 for v in values[1:]])
        else:raise ValueError('Canonical OBJ syntax differs')
    doc=json.loads(corner_raw)
    if set(doc)!= {'version','triangle_count','triangles'} or type(doc['version']) is not int or doc['version']!=1 or type(doc['triangle_count']) is not int or doc['triangle_count']!=len(faces) or not 1<=len(faces)<5000 or len(doc['triangles'])!=len(faces):raise ValueError('Canonical triangle closure')
    mids={m['material_id'] for m in materials}
    for i,(face,tri) in enumerate(zip(faces,doc['triangles'])):
        if set(tri)!={'tri_id','shape_id','material_id','positions','uv0','normals','tangents'} or type(tri['tri_id']) is not int or tri['tri_id']!=i or type(tri['material_id']) is not int or tri['material_id'] not in mids or type(tri['shape_id']) is not str:raise ValueError('Canonical triangle identity')
        if any(not 0<=index<len(vertices) for index in face) or tri['positions']!=[vertices[index] for index in face]:raise ValueError('OBJ/corner position exact mismatch')
        for field,size in (('positions',3),('normals',3),('uv0',2),('tangents',4)):
            if type(tri[field]) is not list or len(tri[field])!=3:raise ValueError('Corner count')
            for vector in tri[field]:
                if vector is None and not require_material and field in ('uv0','tangents'):continue
                if type(vector) is not list or len(vector)!=size:raise ValueError('Corner dimension')
                for v in vector:number(v)
        if require_material:
            signs={v[3] for v in tri['tangents']}
            if len(signs)!=1 or not signs.issubset({-1.,1.}):raise ValueError('Tangent handedness')
            for n,t in zip(tri['normals'],tri['tangents']):
                if sum(v*v for v in n)==0 or sum(v*v for v in t[:3])==0:raise ValueError('Zero normal/tangent')
    return dict(triangle_count=len(faces),positions_exact=True,corner_material_ready=require_material)
