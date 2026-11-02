"""Factor-only pure handler/transport tests; no HTTP server, Blender or native."""
import asyncio,copy,hashlib,json,struct,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server as s,material_revision as m

BASE=Path(__file__).resolve().parent
def sha(raw):return hashlib.sha256(raw).hexdigest()
def glb(doc,binary=b'GEOMETRY_UV_TEXTURE_BIN_0000000000'):
    binary+=b'\0'*((-len(binary))%4)
    encoded=json.dumps(doc).encode();encoded+=b' '*((-len(encoded))%4)
    chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<III',0x46546c67,2,12+len(chunks))+chunks
def specimen(root):
    folder=root/'source';folder.mkdir(parents=True);aid='a'*32
    physics=b'v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
    triangle=dict(tri_id=0,shape_id='TEST_ONLY',material_id=0,positions=[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]],uv0=[[0.,0.],[1.,0.],[0.,1.]],normals=[[0.,0.,1.]]*3,tangents=[[1.,0.,0.,1.]]*3)
    corners=json.dumps(dict(version=1,triangle_count=1,triangles=[triangle])).encode()
    record=dict(material_id=0,base_color_factor=[1.,1.,1.],roughness_factor=1.,metallic_factor=1.,base_color_texture=None,roughness_texture=None,metallic_texture=None,normal_texture=None)
    doc=dict(asset=dict(version='2.0'),buffers=[dict(byteLength=32)],bufferViews=[dict(buffer=0,byteOffset=0,byteLength=32)],materials=[dict(name='ReviewMat_0',pbrMetallicRoughness=dict(baseColorTexture=dict(index=0),metallicRoughnessTexture=dict(index=1)))],meshes=[dict(primitives=[dict(material=0,attributes=dict(POSITION=0,TEXCOORD_0=1))])])
    data=glb(doc)
    for name,raw in [('physics.obj',physics),('corners.json',corners),('scene.glb',data),('original.obj',physics)]: (folder/name).write_bytes(raw)
    manifest=dict(version=1,profile='material',assets=[dict(asset_id=aid,physics_obj_sha256=sha(physics),corner_data_path=str(folder/'corners.json'),corner_data_sha256=sha(corners),materials=[record])],textures=[])
    (folder/'material-manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return dict(asset_id=aid,name='TEST_ONLY factor transport',enabled=True,folder=str(folder),physics=str(folder/'physics.obj'),source=str(folder/'original.obj'),source_hashes={str(folder/'original.obj'):sha(physics)},scale=.25,weight=1.,render_revision=sha(data),material_revision=m.identity([record]),metadata=dict(schema_version=2,material_ready=True,material_records=[record],files={'physics.obj':sha(physics),'corners.json':sha(corners),'scene.glb':sha(data)}),material_manifest=str(folder/'material-manifest.json'),url=f'/api/assets/{aid}/scene.glb')

class MaterialRevision(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory(prefix='ui3b_factors_');self.root=Path(self.temp.name);self.old=specimen(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_factor_json_native_records_and_all_binary_links_preserved(self):
        raw=(Path(self.old['folder'])/'scene.glb').read_bytes();records=self.old['metadata']['material_records'];before=copy.deepcopy(records)
        new,updated=m.edit_glb(raw,records,{'0':dict(base_color_factor=[.25,.5,.75],roughness_factor=.125,metallic_factor=.625)})
        old_doc,old_chunks=m.split_glb(raw);doc,chunks=m.split_glb(new)
        self.assertEqual(chunks[1:],old_chunks[1:]);self.assertEqual(doc['meshes'],old_doc['meshes']);self.assertEqual(doc['bufferViews'],old_doc['bufferViews'])
        p=doc['materials'][0]['pbrMetallicRoughness'];self.assertEqual(p['baseColorFactor'],[.25,.5,.75,1.]);self.assertEqual(p['roughnessFactor'],.125);self.assertEqual(p['metallicFactor'],.625)
        self.assertEqual(p['baseColorTexture'],old_doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']);self.assertEqual(updated[0]['base_color_factor'],p['baseColorFactor'][:3]);self.assertEqual(records,before)
    def test_invalid_factors_mapping_external_resources_and_glb_rejected(self):
        raw=(Path(self.old['folder'])/'scene.glb').read_bytes();records=self.old['metadata']['material_records']
        for edits in ({'0':{}},{'0':{'base_color_factor':[1,2,0]}},{'0':{'roughness_factor':True}},{'0':{'metallic_factor':float('nan')}},{'0':{'normal_strength':1}},{'1':{'roughness_factor':.5}},{'00':{'roughness_factor':.5}}):
            with self.subTest(edits=edits),self.assertRaises(ValueError):m.edit_glb(raw,records,edits)
        doc,chunks=m.split_glb(raw);doc['buffers'][0]['uri']='foreign.bin'
        with self.assertRaises(ValueError):m.edit_glb(glb(doc),records,{'0':{'roughness_factor':.5}})
        with self.assertRaises(ValueError):m.edit_glb(raw[:-1],records,{'0':{'roughness_factor':.5}})
    def test_immutable_revision_same_geometry_and_source_restore(self):
        originals={str(p):p.read_bytes() for p in Path(self.old['folder']).iterdir()}
        new,changed=m.build_revision(self.old,self.root,self.root/'revision1',{'0':dict(base_color_factor=[.2,.4,.6],roughness_factor=.25,metallic_factor=.75)})
        self.assertTrue(changed);self.assertEqual(new['asset_id'],self.old['asset_id']);self.assertEqual(new['physics'],self.old['physics'])
        self.assertEqual(new['metadata']['files']['physics.obj'],self.old['metadata']['files']['physics.obj']);self.assertEqual(new['metadata']['files']['corners.json'],self.old['metadata']['files']['corners.json'])
        self.assertNotEqual(new['render_revision'],self.old['render_revision']);self.assertNotEqual(new['material_revision'],self.old['material_revision'])
        self.assertTrue(all(Path(p).read_bytes()==raw for p,raw in originals.items()))
        restored,_=m.build_revision(new,self.root,self.root/'revision2',new['material_source_factors'])
        self.assertEqual(restored['metadata']['material_records'],self.old['metadata']['material_records'])
        self.assertEqual(restored['material_source_factors'],new['material_source_factors'])
    def test_noop_and_changed_source_reject_without_new_revision(self):
        new,changed=m.build_revision(self.old,self.root,self.root/'noop',{'0':{'roughness_factor':1.}})
        self.assertFalse(changed);self.assertFalse((self.root/'noop').exists());self.assertEqual(new,self.old)
        with self.assertRaises(ValueError):m.build_revision(self.old,self.root,self.root.parent/'FOREIGN_TEST_ONLY',{'0':{'roughness_factor':.5}})
        (Path(self.old['folder'])/'scene.glb').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):m.build_revision(self.old,self.root,self.root/'bad',{'0':{'roughness_factor':.5}})
        self.assertFalse((self.root/'bad').exists())
    def handler(self,body,fail=False):
        catalog={self.old['asset_id']:copy.deepcopy(self.old)};state=self.root/'assets.json';state.write_text(json.dumps(catalog),encoding='utf-8');before=state.read_bytes()
        with patch.multiple(s,WORK=self.root,state_path=state,assets=catalog,lock=asyncio.Lock()),patch.object(s,'is_busy',return_value=False),patch.object(s,'space_budget'):
            if fail:
                with patch.object(s,'write',side_effect=OSError('TEST_ONLY atomic write failure')),self.assertRaises(OSError):asyncio.run(s.edit_material(self.old['asset_id'],body,s.identity(catalog[self.old['asset_id']])))
                self.assertEqual(catalog[self.old['asset_id']],self.old);self.assertEqual(state.read_bytes(),before)
            else:
                result=asyncio.run(s.edit_material(self.old['asset_id'],body,s.identity(catalog[self.old['asset_id']])));self.assertEqual(result['asset_id'],self.old['asset_id']);self.assertEqual(result['metadata']['material_records'][0]['roughness_factor'],.2);self.assertEqual(json.loads(state.read_bytes())[self.old['asset_id']],catalog[self.old['asset_id']])
    def test_direct_handler_success_and_catalog_write_failure_preserve_current(self):
        current=self.root/'current.json';current.write_bytes(b'CURRENT_AND_OLD_JOB_GLB_UNCHANGED')
        body=s.MaterialEdit(factors={'0':dict(roughness_factor=.2)})
        self.handler(body,fail=True);self.assertEqual(current.read_bytes(),b'CURRENT_AND_OLD_JOB_GLB_UNCHANGED')
        self.handler(body);self.assertEqual(current.read_bytes(),b'CURRENT_AND_OLD_JOB_GLB_UNCHANGED')
    def test_factor_request_rejects_invalid_types_and_binding_or_geometry_scope(self):
        for body in ({'factors':{}},{'factors':{'0':{'roughness_factor':True}}},{'factors':{'0':{'base_color_factor':[.1,.2]}}},{'factors':{'0':{'metallic_factor':float('inf')}}},{'factors':{'0':{'texture_id':'a'*64}}},{'factors':{'0':{'roughness_factor':.5}},'units':'cm'}):
            with self.subTest(body=body),self.assertRaises(ValueError):s.MaterialEdit(**body)
    def test_actual_ui_stale_function_and_panel_placement(self):
        code="""import fs from 'node:fs';import assert from 'node:assert/strict';
const source=fs.readFileSync('web/ui2.js','utf8').replace(\"import * as THREE from 'three';\",'');
const {materialStale}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const result={settings:{asset_renders:{a:{glb_sha256:'old',material_revision:'mat1'}}}};
const catalog=[{asset_id:'a',material_revision:'mat2',metadata:{files:{'scene.glb':'new'}}}];
assert.equal(materialStale(result,catalog),true);assert.equal(result.settings.asset_renders.a.glb_sha256,'old');
catalog[0].material_revision='mat1';catalog[0].metadata.files['scene.glb']='old';assert.equal(materialStale(result,catalog),false);
"""
        r=subprocess.run(['node','--input-type=module','-'],input=code,text=True,capture_output=True,cwd=BASE,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr)
        html=(BASE/'web/index.html').read_text('utf-8');self.assertLess(html.index('id="sourceDetails"'),html.index('id="assetList"'))
        app=(BASE/'web/app.js').read_text('utf-8');self.assertIn('materialStale(lastGood,catalog)',app);self.assertIn('pin.glb_sha256',app)

if __name__=='__main__':unittest.main(verbosity=2)
