"""Manual PBR bindings pure GLB/PNG/handler checks; no browser/Blender/native."""
import asyncio,copy,hashlib,io,json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from fastapi import UploadFile
import server as s,texture_revision as t,material_revision as m,pbr_contract as pbr,job_assets
import test_material_revision as factors
BASE=Path(__file__).resolve().parent

def image(color):
    im=Image.new('RGBA',(512,512),color);im.putpixel((511,0),(91,52,199,255));return t.png(im)
def texture(root,name,raw,manual=False):
    path=root/(name+'.png');path.write_bytes(raw);h=pbr.sha(raw);row=dict(texture_id=h,path=str(path),content_sha256=h,width=512,height=512,channels=4,bit_depth=8)
    if manual:row.update(source_path=str(path),source_sha256=h,source_name=name+'.png',source_kind='manual_uploaded')
    return row

def extracted(raw,reference):
    d,c=m.split_glb(raw);im=d['images'][d['textures'][reference['index']]['source']];v=d['bufferViews'][im['bufferView']];return t.rgba(c[1][1][v['byteOffset']:v['byteOffset']+v['byteLength']])

class TextureRevision(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='manual_texture_');self.root=Path(self.temp.name);self.old=factors.specimen(self.root);folder=Path(self.old['folder']);physical=Path(self.old['physics']);physical.write_bytes(physical.read_bytes().replace(b'f 1 2 3',b'v 0 0 1\nf 1 2 3'));self.old['metadata']['files']['physics.obj']=pbr.sha(physical.read_bytes());doc,chunks=m.split_glb((folder/'scene.glb').read_bytes());doc['meshes'][0]['primitives'][0]['attributes'].update(NORMAL=2,TANGENT=3);doc['buffers'][0]['byteLength']=len(chunks[1][1]);raw=factors.glb(doc)
        original=[texture(folder,'source_bc',image((12,24,48,255))),texture(folder,'source_rm',image((17,29,43,255)))];self.manual=[texture(self.root,'manual_bc',image((127,65,33,255)),True),texture(self.root,'manual_pack',image((37,111,203,255)),True),texture(self.root,'manual_normal',image((64,37,230,255)),True)]
        record=self.old['metadata']['material_records'][0];record.update(base_color_factor=[.125,.5,1.],roughness_factor=.25,metallic_factor=.5)
        doc,_=m.split_glb(raw);doc['materials'][0]['pbrMetallicRoughness'].update(baseColorFactor=[.125,.5,1.,1.],roughnessFactor=.25,metallicFactor=.5);raw=factors.glb(doc)
        source={'0':{r+'_texture':None for r in t.ROLES}};settings={'0':dict(base_color=dict(mode='texture',texture_id=original[0]['texture_id']),roughness=dict(mode='texture',texture_id=original[1]['texture_id'],channel='r'),metallic=dict(mode='texture',texture_id=original[1]['texture_id'],channel='g'))}
        read=lambda path,h,limit:Path(path).read_bytes();raw,records=t.edit_glb(raw,[record],settings,source,{r['texture_id']:r for r in original},read)
        (folder/'scene.glb').write_bytes(raw);self.old['metadata']['files']['scene.glb']=pbr.sha(raw);self.old['render_revision']=pbr.sha(raw);self.old['metadata']['material_records']=records;self.old['material_revision']=m.identity(records);self.old['manual_textures']=self.manual
        self.old['metadata']['materials']=[dict(material_id=0,name='TEST_ONLY',roles={r:dict(status='texture',binding=records[0][r+'_texture']) for r in t.ROLES})]
        manifest=json.loads(Path(self.old['material_manifest']).read_bytes());manifest['textures']=original;manifest['assets'][0]['materials']=records;manifest['assets'][0]['physics_obj_sha256']=self.old['metadata']['files']['physics.obj'];Path(self.old['material_manifest']).write_text(json.dumps(manifest),encoding='utf8')
        for row in original:self.old['source_hashes'][row['path']]=row['content_sha256']
        self.edits={'0':dict(base_color=dict(mode='texture',texture_id=self.manual[0]['texture_id'],color_space='linear'),roughness=dict(mode='texture',texture_id=self.manual[1]['texture_id'],channel='b'),metallic=dict(mode='texture',texture_id=self.manual[1]['texture_id'],channel='g'),normal=dict(mode='texture',texture_id=self.manual[2]['texture_id'],normal_convention='DirectX'))}
    def tearDown(self):self.temp.cleanup()
    def revision(self):return m.build_revision(self.old,self.root,self.root/'revision',{},bindings=self.edits)[0]
    def test_GLB_append_channels_DX_once_no_doublefactor_and_geometry_identity(self):
        raw=Path(self.old['folder'],'scene.glb').read_bytes();doc,chunks=m.split_glb(raw);originals={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()};new=self.revision();newraw=Path(new['folder'],'scene.glb').read_bytes();d,c=m.split_glb(newraw)
        self.assertEqual(c[1][1][:len(chunks[1][1])],chunks[1][1]);self.assertEqual(d['meshes'],doc['meshes']);self.assertEqual(d.get('accessors'),doc.get('accessors'));self.assertEqual(d['bufferViews'][:len(doc['bufferViews'])],doc['bufferViews']);self.assertEqual(new['physics'],self.old['physics']);self.assertEqual(new['asset_id'],self.old['asset_id']);self.assertEqual(new['metadata']['files']['corners.json'],self.old['metadata']['files']['corners.json'])
        mat=d['materials'][0];mr=mat['pbrMetallicRoughness'];self.assertEqual(extracted(newraw,mr['metallicRoughnessTexture']).getpixel((0,0)),(255,203,111,255));self.assertEqual(extracted(newraw,mat['normalTexture']).getpixel((0,0)),(64,218,230,255));self.assertEqual(extracted(newraw,mat['normalTexture']).getpixel((511,0)),(91,203,199,255));self.assertEqual(mr['baseColorFactor'],[.125,.5,1.,1.]);self.assertEqual(mr['roughnessFactor'],.25);self.assertEqual(mr['metallicFactor'],.5);self.assertEqual(mat['extras']['review_texture_preview'],dict(version=1,base_color_space='linear'))
        refs=[mr['baseColorTexture']['index'],mr['metallicRoughnessTexture']['index'],mat['normalTexture']['index']];self.assertEqual(len(set(refs)),3)
        for view in d['bufferViews'][len(doc['bufferViews']):]:self.assertEqual(view['byteOffset']%4,0);self.assertLessEqual(view['byteOffset']+view['byteLength'],d['buffers'][0]['byteLength'])
        self.assertTrue(all(p.read_bytes()==r for p,r in originals.items()));manifest=json.loads(Path(new['material_manifest']).read_bytes());pbr.validate_manifest(manifest,{new['asset_id']:new['physics']},self.root)
        run=self.root/'jobs/runs'/('b'*32);run.mkdir(parents=True);q=dict(job_id=run.name,operation='bake',output_directory=str(run),assets=[dict(asset_id=new['asset_id'],path=new['physics'],content_hash=new['metadata']['files']['physics.obj'])]);sealed,_,index=job_assets.seal([new],q,self.root,lambda *_:None);self.assertTrue(sealed['review_v1']['bake_pbr']);job_assets.verify(index,self.root,True)
        normal=next(row for row in index['files'] if row['role']=='texture' and row['sha256']==self.manual[2]['content_sha256']);self.assertEqual(t.rgba(Path(normal['path']).read_bytes()).getpixel((0,0)),(64,37,230,255));self.assertTrue(any(row['role']=='original' and row['source_path']==self.manual[2]['source_path'] for row in index['files']))

    def test_Auto_restores_first_source_bindings_and_preserves_current_factors(self):
        new=self.revision();source=new['material_source_bindings'];self.assertEqual(source['0']['normal_texture'],None);self.assertEqual(source['0']['base_color_texture'],self.old['metadata']['material_records'][0]['base_color_texture'])
        restore={'0':{r:dict(mode='auto') for r in t.ROLES}};restored,_=m.build_revision(new,self.root,self.root/'restored',{},bindings=restore);self.assertEqual(restored['metadata']['material_records'],self.old['metadata']['material_records']);self.assertEqual(restored['material_source_bindings'],source);d,_=m.split_glb(Path(restored['folder'],'scene.glb').read_bytes());self.assertNotIn('normalTexture',d['materials'][0]);self.assertEqual(d['materials'][0]['pbrMetallicRoughness']['baseColorFactor'],[.125,.5,1.,1.])
    def test_missing_UV_TANGENT_unknown_binding_and_changed_original_fail(self):
        raw=Path(self.old['folder'],'scene.glb').read_bytes();d,c=m.split_glb(raw)
        for attr in ('TEXCOORD_0','TANGENT'):
            changed=copy.deepcopy(d);changed['meshes'][0]['primitives'][0]['attributes'].pop(attr);data=factors.glb(changed,c[1][1]);manifest=json.loads(Path(self.old['material_manifest']).read_bytes());available=t.library(self.old,manifest);source={'0':{r+'_texture':None for r in t.ROLES}}
            with self.assertRaises(ValueError):t.edit_glb(data,self.old['metadata']['material_records'],self.edits,source,available,lambda path,*_:Path(path).read_bytes())
        for edit in ({'9':{'normal':{'mode':'none'}}},{'0':{'base_color':{'mode':'texture','texture_id':'0'*64}}},{'0':{'normal':{'mode':'auto','texture_id':self.manual[0]['texture_id']}}},{'0':{'roughness':{'mode':'texture','texture_id':self.manual[1]['texture_id'],'color_space':'sRGB'}}}):
            with self.assertRaises(ValueError):m.build_revision(self.old,self.root,self.root/'invalid',{},bindings=edit)
        Path(self.manual[0]['source_path']).write_bytes(b'CHANGED')
        with self.assertRaises(ValueError):self.revision()
    def test_channel_preview_is_raw_component_without_source_changes(self):
        raw=Path(self.manual[1]['path']).read_bytes();preview=t.rgba(t.channel_preview(raw,'g'));self.assertEqual(preview.getpixel((0,0)),(111,111,111,255));self.assertEqual(Path(self.manual[1]['path']).read_bytes(),raw)
        with self.assertRaises(ValueError):t.channel_preview(raw,'a')
    def test_upload_canonicalizes_once_and_invalid_or_cancel_keeps_catalog_current(self):
        old=copy.deepcopy(self.old);catalog={old['asset_id']:old};state=self.root/'assets.json';state.write_text(json.dumps(catalog),encoding='utf8');current=self.root/'current.json';current.write_bytes(b'CURRENT')
        async def exercise():
            with patch.multiple(s,WORK=self.root,state_path=state,assets=catalog,lock=asyncio.Lock()),patch.object(s,'is_busy',return_value=False),patch.object(s,'space_budget'):
                jpeg=io.BytesIO();Image.new('RGB',(512,512),(14,82,176)).save(jpeg,format='JPEG');raw=jpeg.getvalue();upload=UploadFile(filename='added.jpg',file=io.BytesIO(raw));revised=await s.upload_textures(old['asset_id'],[upload]);self.assertEqual(revised['render_revision'],old['render_revision']);self.assertEqual(revised['metadata'],old['metadata']);row=revised['manual_textures'][-1];self.assertEqual(Path(row['source_path']).read_bytes(),raw);self.assertEqual(t.rgba(Path(row['path']).read_bytes()).tobytes(),Image.open(io.BytesIO(raw)).convert('RGBA').tobytes())
                before=state.read_bytes();bad=io.BytesIO();Image.new('RGB',(128,128)).save(bad,format='PNG')
                with self.assertRaises(ValueError):await s.upload_textures(old['asset_id'],[UploadFile(filename='bad.png',file=io.BytesIO(bad.getvalue()))])
                self.assertEqual(state.read_bytes(),before)
                disguised=io.BytesIO();Image.new('RGB',(512,512)).save(disguised,format='BMP')
                with self.assertRaises(ValueError):await s.upload_textures(old['asset_id'],[UploadFile(filename='disguised.png',file=io.BytesIO(disguised.getvalue()))])
                self.assertEqual(state.read_bytes(),before)
                class Cancelled:
                    filename='cancel.png'
                    async def read(self,n):raise asyncio.CancelledError()
                with self.assertRaises(asyncio.CancelledError):await s.upload_textures(old['asset_id'],[Cancelled()])
                self.assertEqual(state.read_bytes(),before);self.assertEqual(current.read_bytes(),b'CURRENT')
        asyncio.run(exercise())
    def test_binding_handler_atomic_adoption_failure_preserves_old_revision(self):
        catalog={self.old['asset_id']:copy.deepcopy(self.old)};state=self.root/'assets.json';state.write_text(json.dumps(catalog),encoding='utf8');before=state.read_bytes()
        with patch.multiple(s,WORK=self.root,state_path=state,assets=catalog,lock=asyncio.Lock()),patch.object(s,'is_busy',return_value=False),patch.object(s,'space_budget'),patch.object(s,'write',side_effect=OSError('TEST_ONLY catalog failure')):
            with self.assertRaises(OSError):asyncio.run(s.edit_material(self.old['asset_id'],s.MaterialEdit(bindings=self.edits)))
        self.assertEqual(state.read_bytes(),before);self.assertEqual(catalog[self.old['asset_id']],self.old)
    def test_Three_declared_colorspace_clones_and_draft_preserved(self):
        script=r"""import * as THREE from 'three';import {applyTextureColorSpaces} from './web/ui2.js';import fs from 'node:fs';import assert from 'node:assert/strict';
const shared=new THREE.Texture();shared.colorSpace=THREE.SRGBColorSpace;const material=new THREE.MeshStandardMaterial({map:shared,roughnessMap:shared,metalnessMap:shared,normalMap:shared});material.userData.review_texture_preview={version:1,base_color_space:'linear'};const root=new THREE.Group();root.add(new THREE.Mesh(new THREE.BufferGeometry(),material));applyTextureColorSpaces(root);assert.equal(material.map.colorSpace,THREE.NoColorSpace);assert.equal(shared.colorSpace,THREE.SRGBColorSpace);assert.notEqual(material.map,material.normalMap);assert.equal(material.normalMap.colorSpace,THREE.NoColorSpace);material.userData.review_texture_preview.version=2;assert.throws(()=>applyTextureColorSpaces(root));
const app=fs.readFileSync('web/app.js','utf8'),drafts=new Map();const draft=eval('('+app.match(/function draft\(a\)\{[^\n]+/)[0]+')');const a={asset_id:'a',scale:1,weight:1,metadata:{units:'m',source_up_axis:'Z'},render_revision:'old'};const d=draft(a);Object.assign(d,{scale:2.75,weight:8,selected:false,material_bindings:{old:1}});a.render_revision='new';assert.equal(draft(a).scale,2.75);assert.equal(d.weight,8);assert.equal(d.selected,false);assert.equal(d.material_bindings,undefined);
"""
        r=subprocess.run(['node','--input-type=module','-'],input=script,text=True,encoding='utf8',capture_output=True,cwd=BASE,timeout=15);self.assertEqual(r.returncode,0,r.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
