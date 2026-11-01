"""UI2 pure metadata/geometry/artifact boundaries. No Blender/native/browser executions."""
import ast,hashlib,json,struct,unittest,uuid,zlib
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import import_contract as c,canonical_contract as g,server as s

BASE=Path(__file__).resolve().parent
class UI2(unittest.TestCase):
    def setUp(self):self.root=BASE/'test-output'/uuid.uuid4().hex;self.root.mkdir(parents=True)
    def test_fbx_auto_and_override_apply_units_once(self):
        globals=dict(UnitScaleFactor=1.,UpAxis=2,UpAxisSign=1,FrontAxis=1,FrontAxisSign=-1,CoordAxis=0,CoordAxisSign=1);info={'globals':globals}
        a=c.unit_policy(info,'auto','m','Z','Y');b=c.unit_policy(info,'override','m','Z','Y');self.assertEqual(a['global_scale'],1);self.assertEqual(b['global_scale']*(globals['UnitScaleFactor']/100),1);self.assertFalse(a['post_import_unit_axis_transform'])
        with self.assertRaises(ValueError):c.unit_policy(info,'override','m','Y','-Y')
        with self.assertRaises(ValueError):c.unit_policy({'globals':dict(globals,UnitScaleFactor=True)},'auto','m','Z','Y')
    def test_real_fbx_metadata_readonly_no_import(self):
        fixtures=[BASE.parent/'output/evidence/fbx-risk-fixtures/33ba774a09f64186a29a94268cfdaee9/A/owned-locators-only.fbx',BASE.parent/'output/evidence/fbx-risk-fixtures/00fd1319990547d383950c1c133c15d5/B/TEST_ONLY_hierarchy.fbx']
        for path in fixtures:
            before=hashlib.sha256(path.read_bytes()).hexdigest();info=c.source_info(path);self.assertGreater(info['node_count'],0);self.assertEqual(info['source_sha256'],before);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.assertTrue(any(r.get('Content') for r in c.source_info(fixtures[0])['images']))
    def test_images_are_512_raw_derivatives_with_role_safe_dx_copy(self):
        source=self.root/'one.obj';source.write_text('v 0 0 0',encoding='utf8');image=self.root/'data.png';Image.new('RGB',(512,512),(64,128,192)).save(image);before=image.read_bytes();out=self.root/'out';out.mkdir();registry=c.prepare_images(source,out);tid=registry['textures'][0]['texture_id'];out2=self.root/'out2';out2.mkdir();other=c.prepare_images(source,out2,dx_ids=[tid]);row=other['textures'][0]
        self.assertEqual(image.read_bytes(),before);self.assertEqual(Image.open(row['path']).getpixel((0,0)),(64,128,192,255));self.assertEqual(Image.open(row['preview_dx_path']).getpixel((0,0)),(64,127,192,255));self.assertEqual(row['content_sha256'],tid)
        Image.new('RGB',(256,256)).save(self.root/'bad.png');out3=self.root/'out3';out3.mkdir()
        with self.assertRaisesRegex(ValueError,'512'):c.prepare_images(source,out3)
    def test_actual_embedded_texture_records_before_video_payloads(self):
        fixture=BASE.parent/'output/evidence/fbx-risk-fixtures/33ba774a09f64186a29a94268cfdaee9/A/owned-locators-only.fbx';raw=fixture.read_bytes();info=c.source_info(fixture)
        self.assertEqual([bool(r.get('Content')) for r in info['images']],[False]*3+[True]*3)
        # A single uploaded FBX: no external textures reside next to this owned copy.
        source=self.root/'only.fbx';source.write_bytes(raw);out=self.root/'out';out.mkdir();registry=c.prepare_images(source,out,info)
        names={__import__('ntpath').basename((r.get('RelativeFilename') or r.get('FileName') or r.get('Filename')).replace('/','\\')).casefold() for r in info['images']}
        self.assertEqual(set(registry['bindings']),names);self.assertEqual(len(registry['textures']),3);self.assertTrue(all(t['source_kind']=='embedded' for t in registry['textures']));self.assertEqual(fixture.read_bytes(),raw)
        # Registration still rejects conflicting payloads and unresolved locators.
        import copy
        corrupt=copy.deepcopy(info);other=self.root/'conflict.png';Image.new('RGB',(512,512),(1,2,3)).save(other);payload=other.read_bytes();other.unlink();duplicate=copy.deepcopy(corrupt['images'][-1]);duplicate['Content']=payload;corrupt['images'].append(duplicate);bad=self.root/'bad';bad.mkdir()
        with self.assertRaisesRegex(ValueError,'Ambiguous duplicate'):c.prepare_images(source,bad,corrupt)
        missing=copy.deepcopy(info);missing['images'].append(dict(FileName='absent.png'));bad2=self.root/'bad2';bad2.mkdir()
        with self.assertRaisesRegex(ValueError,'Missing'):c.prepare_images(source,bad2,missing)
    def test_embedded_missing_locator_uses_owned_bytes_only(self):
        source=self.root/'owned.fbx';source.write_bytes(b'not imported');out=self.root/'out';out.mkdir();image=self.root/'temporary.png';Image.new('RGB',(512,512),(1,2,3)).save(image);raw=image.read_bytes();image.unlink()
        info={'images':[dict(FileName='C:/outside/never-opened.png',Content=raw)]};r=c.prepare_images(source,out,info);self.assertEqual(r['textures'][0]['source_kind'],'embedded');self.assertTrue(Path(r['textures'][0]['path']).is_relative_to(out))
        out2=self.root/'out2';out2.mkdir()
        with self.assertRaisesRegex(ValueError,'Missing'):c.prepare_images(source,out2,{'images':[dict(FileName='C:/outside/missing.png')]})
    def test_corner_obj_position_exact_and_no_hidden_triangulation(self):
        obj=b'v 0.1 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n';positions=[[g.f32(.1),0,0],[1,0,0],[0,1,0]];doc=dict(version=1,triangle_count=1,triangles=[dict(tri_id=0,shape_id='part_0',material_id=0,positions=positions,uv0=[[0,0],[1,0],[0,1]],normals=[[0,0,1]]*3,tangents=[[1,0,0,1]]*3)])
        self.assertTrue(g.validate(obj,json.dumps(doc).encode(),[{'material_id':0}],True)['positions_exact']);doc['triangles'][0]['positions'][0][0]+=.00001
        with self.assertRaisesRegex(ValueError,'exact'):g.validate(obj,json.dumps(doc).encode(),[{'material_id':0}],True)
    def test_manual_role_models_no_unknown_or_data_srgb(self):
        valid=s.Normalization(material_overrides={'0':{'metallic':{'mode':'texture','texture_id':'a'*64,'channel':'b','color_space':'linear'}}});self.assertEqual(valid.material_overrides['0']['metallic'].channel,'b')
        for bad in ({'0':{'metallic':{'mode':'texture','texture_id':'a'*64,'color_space':'sRGB'}}},{'../':{}},{'0':{'unknown':{}}}):
            with self.assertRaises(ValueError):s.Normalization(material_overrides=bad)
        with self.assertRaises(ValueError):s.Run.model_validate(dict(assets=[dict(asset_id=f'{i:032x}',scale=1.,weight=0.) for i in range(7)],simulation={},bake={}))
    def test_n1_verifier_functions_are_reused_exactly(self):
        source=(BASE.parent/'tests/test_review_native.py').read_text(encoding='utf8');copy=(BASE/'review_contract.py').read_text(encoding='utf8');a={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)};b={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(copy).body if isinstance(n,ast.FunctionDef)};self.assertEqual(a,b)
    def test_converter_source_has_no_double_unit_transform_for_fbx(self):
        text=(BASE/'convert_asset.py').read_text(encoding='utf8');self.assertIn('return Matrix.Identity(4)',text);self.assertIn("image_utils.load_image=original",text);self.assertIn("check_existing=False",text);self.assertIn("'Non-Color'",text);self.assertNotIn('bmesh',text)
        js=(BASE/'web/ui2.js').read_text(encoding='utf8');self.assertIn('mesh.position.fromArray(pose.position)',js);self.assertNotIn('mesh.scale.',js)
    def auto_texture_function(self):
        tree=ast.parse((BASE/'convert_asset.py').read_text(encoding='utf8'));nodes=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='array' or isinstance(n,ast.FunctionDef) and n.name=='auto_texture'];ns={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'auto_texture-focused','exec'),ns);return ns['auto_texture']
    def test_scalar_texture_bulk_read_once_and_exact_rgb(self):
        from types import SimpleNamespace as N
        class Pixels:
            def __init__(self,values):self.values=values;self.copies=0
            def __len__(self):return len(self.values)
            def __getitem__(self,index):raise AssertionError('RNA scalar read forbidden')
            def foreach_get(self,target):
                self.copies+=1
                for i,value in enumerate(self.values):target[i]=value
        pixels=Pixels([.5,.5,.5,1.,.25,.25,.25,1.]);image=N(pixels=pixels);node=N(bl_idname='ShaderNodeTexImage',image=image,projection='FLAT',extension='REPEAT',inputs={'Vector':N(is_linked=False)});socket=N(is_linked=True,links=[N(from_node=node)])
        run=self.auto_texture_function();self.assertEqual(run(socket,'roughness')['channel'],'r');self.assertEqual(pixels.copies,1)
        pixels.values[1]=.5000000596046448
        with self.assertRaisesRegex(ValueError,'packed channel'):run(socket,'metallic')
        self.assertEqual(pixels.copies,2)
    def test_empty_tangent_normal_falls_back_but_real_unsupported_stays_error(self):
        from types import SimpleNamespace as N
        strength=N(is_linked=False,default_value=1.);color=N(is_linked=False,default_value=(.5,.5,1.,1.),links=[]);node=N(bl_idname='ShaderNodeNormalMap',space='TANGENT',inputs={'Strength':strength,'Color':color});socket=N(is_linked=True,links=[N(from_node=node)]);run=self.auto_texture_function()
        self.assertIsNone(run(socket,'normal'));color.default_value=(.5,.6,1.,1.)
        with self.assertRaisesRegex(ValueError,'Normal'):run(socket,'normal')
        strength.default_value=0;self.assertIsNone(run(socket,'normal'))
        strength.default_value=.5;color.is_linked=True;color.links=[N(from_node=N(bl_idname='ShaderNodeTexImage'))]
        with self.assertRaisesRegex(ValueError,'Normal'):run(socket,'normal')
        strength.default_value=1;color.links=[N(from_node=N(bl_idname='ShaderNodeNoiseTexture'))]
        with self.assertRaisesRegex(ValueError,'Procedural'):run(socket,'normal')
        color.is_linked=False;color.default_value=(.5,.5,1.,1.);strength.is_linked=True
        with self.assertRaisesRegex(ValueError,'Normal'):run(socket,'normal')
        strength.is_linked=False;node.space='OBJECT'
        with self.assertRaisesRegex(ValueError,'Normal'):run(socket,'normal')

if __name__=='__main__':unittest.main()
