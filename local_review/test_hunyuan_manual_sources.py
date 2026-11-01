"""Preset manual-origin regression. Pure handler/temp files; no HTTP/runtime edits.
The unchanged hardcoded library fingerprint gate is stubbed only for synthetic
library JSON; all original/manual file SHA and owner checks use real bytes.
"""
import asyncio,copy,hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import server as s

class HunyuanManualSources(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='preset_manual_');self.root=Path(self.temp.name);self.work=self.root/'work';self.work.mkdir();self.library=self.root/'library/asset_library.json';self.library.parent.mkdir();self.assets={};rows=[]
        real=hashlib.sha256
        for name,aid in s.READY_PRESETS.items():
            ext=self.library.parent/name;ext.mkdir();owned=self.work/aid;owned.mkdir();original={};entries=[]
            for suffix in ('obj','mtl','bc.png','r.png','m.png'):
                basename=name+'.'+suffix;raw=(name+' '+suffix).encode();path=ext/basename;path.write_bytes(raw);copy_path=owned/basename;copy_path.write_bytes(raw);h=real(raw).hexdigest();original[str(copy_path)]=h;entries.append(dict(path=str(path),sha256=h))
            rows.append(dict(asset_id=name,files=dict(obj=entries[0],mtl=entries[1]),textures=dict(zip(('bc','r','m'),entries[2:]))));self.assets[aid]=dict(enabled=True,metadata=dict(material_ready=True,triangles=10),material_manifest='TEST_ONLY ready marker',source_hashes=original,name=name)
        self.raw=json.dumps(dict(assets=rows)).encode();self.library.write_bytes(self.raw);self.aid=next(iter(s.READY_PRESETS.values()));self.real_hash=real
    def tearDown(self):self.temp.cleanup()
    def run_preset(self):
        def digest(raw=b'',*args,**kwargs):
            if raw==self.raw:return SimpleNamespace(hexdigest=lambda:'ac992e43b6438b0c3f71315ef66ead1f163e50adf312c694f7baa063588f4acd')
            return self.real_hash(raw,*args,**kwargs)
        with patch.multiple(s,WORK=self.work,PRESET_LIBRARY=self.library,assets=self.assets),patch.object(s.hashlib,'sha256',digest):return asyncio.run(s.hunyuan_six())
    def manual(self):
        a=self.assets[self.aid];a['manual_textures']=[]
        for i in range(3):
            folder=self.work/('manual'+str(i));folder.mkdir();source=folder/'manual.png';provenance=folder/'manual-info.json';source.write_bytes(('raw '+str(i)).encode());provenance.write_bytes(('info '+str(i)).encode());row=dict(source_path=str(source),source_sha256=self.real_hash(source.read_bytes()).hexdigest(),provenance_path=str(provenance),provenance_sha256=self.real_hash(provenance.read_bytes()).hexdigest());a['manual_textures'].append(row);a['source_hashes'][str(source)]=row['source_sha256'];a['source_hashes'][str(provenance)]=row['provenance_sha256']
        return a
    def test_original_five_remain_valid(self):self.assertEqual(len(self.run_preset()['assets']),6)
    def test_registered_three_pairs_and_Auto_retained_extras_are_valid(self):
        a=self.manual();self.assertEqual(len(a['source_hashes']),11);self.assertEqual(len(self.run_preset()['assets']),6)
        a['metadata']['material_records']=[dict(base_color_texture='original',roughness_texture='original',metallic_texture='original',normal_texture=None)];a['material_source_bindings']={'0':dict(normal_texture=None)}
        self.assertEqual(len(self.run_preset()['assets']),6)
    def test_unregistered_otherpath_wronghash_or_orphan_pair_rejected(self):
        a=self.manual();baseline=copy.deepcopy(self.assets)
        for kind in ('unregistered','otherpath','wronghash','orphan'):
            self.assets=copy.deepcopy(baseline);a=self.assets[self.aid];row=a['manual_textures'][0]
            if kind=='unregistered':a['source_hashes'][str(self.work/'unknown.bin')]='0'*64
            elif kind=='otherpath':
                path=self.work/'different.png';path.write_bytes(Path(row['source_path']).read_bytes());a['source_hashes'][str(path)]=a['source_hashes'].pop(row['source_path'])
            elif kind=='wronghash':a['source_hashes'][row['source_path']]='0'*64
            else:a['source_hashes'].pop(row['provenance_path'])
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.run_preset()
    def test_duplicate_registration_and_canonical_path_alias_rejected(self):
        self.manual();baseline=copy.deepcopy(self.assets);a=self.assets[self.aid];a['manual_textures'].append(copy.deepcopy(a['manual_textures'][0]))
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_preset()
        self.assets=copy.deepcopy(baseline);a=self.assets[self.aid];row=a['manual_textures'][0];path=Path(row['source_path']);alias=str(path.parent/'sub'/'..'/path.name);a['source_hashes'][alias]=row['source_sha256']
        with self.assertRaisesRegex(ValueError,'duplicate'):self.run_preset()
    def test_original_missing_or_SHA_change_still_rejected(self):
        self.manual();baseline=copy.deepcopy(self.assets);a=self.assets[self.aid];original=next(p for p in a['source_hashes'] if p.endswith('.obj'));a['source_hashes'].pop(original)
        with self.assertRaisesRegex(ValueError,'originals differ'):self.run_preset()
        self.assets=copy.deepcopy(baseline);Path(original).write_bytes(b'CHANGED ORIGINAL')
        with self.assertRaisesRegex(ValueError,'source/final_clean SHA'):self.run_preset()

if __name__=='__main__':unittest.main(verbosity=2)
