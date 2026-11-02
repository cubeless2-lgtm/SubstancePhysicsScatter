import hashlib,struct,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter.designer_external import verify_files
class ExternalFiles(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  base=Path(self.tmp.name);identifier='scatter_'+'b'*32;self.root=base/'test_PhysicsScatter'/identifier;self.job='a'*32;self.host=SimpleNamespace(result_directory=lambda graph:self.root)
  self.graph=SimpleNamespace(getIdentifier=lambda:identifier,getPackage=lambda:SimpleNamespace(getFilePath=lambda:str(base/'test.sbs')))
  self.directory=self.root/'external'/self.job;self.directory.mkdir(parents=True)
  self.files={};self.maps={}
  for role,color,bits,space in [('height',0,16,'linear'),('normal',2,8,'linear'),('coverage',0,8,'linear')]:
   data=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>IIBBBBB',64,64,bits,color,0,0,0)+b'\x00'*4
   p=self.directory/(role+'.png');p.write_bytes(data);self.files[role]=p
   d=dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),width=64,height=64,bit_depth=bits,color_type='RGB' if color==2 else 'GREY',color_space=space,format='PNG')
   if role=='normal':d.update(normal_convention='OpenGL',normal_space='object/canonical XYZ')
   self.maps[role]=d
  self.manifest=dict(schema_version=1,job_id=self.job,maps=self.maps,height_min=0,height_max=1)
 def test_sealed_inputs_and_tamper(self):
  self.assertEqual(verify_files(self.graph,self.manifest,self.files,self.host)[1],64)
  self.files['height'].write_bytes(b'changed')
  with self.assertRaises(ValueError):verify_files(self.graph,self.manifest,self.files,self.host)
 def test_mixed_or_foreign_bundle_rejected(self):
  maps=dict(self.files);maps.pop('normal')
  with self.assertRaises(ValueError):verify_files(self.graph,self.manifest,maps,self.host)
  foreign=self.root/'height.png';foreign.write_bytes(self.files['height'].read_bytes());maps=dict(self.files,height=foreign)
  with self.assertRaises(ValueError):verify_files(self.graph,self.manifest,maps,self.host)
if __name__=='__main__':unittest.main()
