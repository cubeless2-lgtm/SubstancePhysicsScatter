import sys,tempfile,threading,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'plugin'))
from substance_physics_scatter.viewer_settings import build_draft,verify_receipt,snapshot_asset_bundle,snapshot_texture_bundle,close_upload_devices,current_material_bindings,material_edit_body,material_conflicts
class DesignerViewerSettings(unittest.TestCase):
 def test_draft_identity_and_race(self):
  row=dict(asset_id='a'*32,enabled=True,render_revision='r',material_revision='m',metadata={'files':{'physics.obj':'p'}},choice_scale=1.0,choice_weight=2.0)
  body,revisions=build_draft([row],{'count':1},{'resolution':64})
  receipt=dict(revision='b'*32,asset_revisions=revisions,current_job_id=None,settings=body)
  self.assertEqual(verify_receipt(receipt,revisions,None,body),'b'*32)
  receipt['asset_revisions']={'a'*32:dict(revisions['a'*32],material_revision='changed')}
  with self.assertRaises(ValueError):verify_receipt(receipt,revisions,None,body)
 def test_invalid_selection(self):
  with self.assertRaises(ValueError):build_draft([],{}, {})
  row=dict(asset_id='a'*32,enabled=True,metadata={},choice_scale=1,choice_weight=0)
  with self.assertRaises(ValueError):build_draft([row],{}, {})
  with self.assertRaises(ValueError):build_draft([dict(row,choice_weight=1)]*2,{}, {})
 def test_explicit_asset_bundle_preserves_input_and_rejects_ambiguous(self):
  with tempfile.TemporaryDirectory() as path:
   root=Path(path);mesh=root/'brick.obj';mtl=root/'brick.mtl';mesh.write_bytes(b'v 0 0 0\n');mtl.write_bytes(b'newmtl brick\n')
   dest=root/'snapshot';dest.mkdir();files=snapshot_asset_bundle([str(mesh),str(mtl)],dest)
   self.assertEqual([(p.name,p.read_bytes()) for p in files],[('brick.obj',b'v 0 0 0\n'),('brick.mtl',b'newmtl brick\n')]);self.assertEqual(mesh.read_bytes(),b'v 0 0 0\n')
   rejected=root/'rejected';rejected.mkdir()
   with self.assertRaises(ValueError):snapshot_asset_bundle([str(mesh),str(mesh)],rejected)
   other=root/'other.fbx';other.write_bytes(b'fbx')
   second=root/'second';second.mkdir()
   with self.assertRaises(ValueError):snapshot_asset_bundle([str(mesh),str(other)],second)
   stopped=threading.Event();stopped.set();cancelled=root/'cancelled';cancelled.mkdir()
   with self.assertRaises(InterruptedError):snapshot_asset_bundle([str(mesh)],cancelled,stopped)
   self.assertEqual(list(cancelled.iterdir()),[]);self.assertEqual(mesh.read_bytes(),b'v 0 0 0\n')
 def test_destroyed_and_failing_devices_do_not_prevent_other_cleanup(self):
  class Device:
   def __init__(self,fail=False):self.closed=False;self.fail=fail
   def close(self):
    if self.fail:raise RuntimeError('deleted Qt object')
    self.closed=True
  destroyed=Device();broken=Device(True);last=Device()
  errors=close_upload_devices([destroyed,broken,last],lambda item:item is not destroyed)
  self.assertEqual(len(errors),1);self.assertFalse(destroyed.closed);self.assertTrue(last.closed)
 def test_material_binding_channel_and_color_contract(self):
  tid='f'*64;record={role+'_texture':None for role in ('base_color','roughness','metallic','normal')}
  record['normal_texture']=dict(texture_id=tid,channel='rgb',color_space='linear',wrap_u='repeat',normal_convention='DirectX')
  bindings=current_material_bindings(record);bindings['roughness']=dict(mode='texture',texture_id=tid,channel='g',color_space='linear',wrap='clamp')
  result=material_edit_body(0,bindings)['bindings']['0']
  self.assertEqual(result['normal']['normal_convention'],'DirectX');self.assertEqual(result['roughness']['channel'],'g')
  bindings['roughness']['color_space']='sRGB'
  with self.assertRaises(ValueError):material_edit_body(0,bindings)
  bindings['roughness']['color_space']='linear';bindings['normal']['normal_convention']='unknown'
  with self.assertRaises(ValueError):material_edit_body(0,bindings)
 def test_texture_snapshot_preserves_source_and_rejects_duplicate(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'albedo.png';source.write_bytes(b'original');dest=root/'dest';dest.mkdir()
   self.assertEqual(snapshot_texture_bundle([str(source)],dest)[0].read_bytes(),b'original');self.assertEqual(source.read_bytes(),b'original')
   other=root/'other';other.mkdir()
   with self.assertRaises(ValueError):snapshot_texture_bundle([str(source),str(source)],other)
 def test_different_role_edit_preserved_and_same_role_conflicts(self):
  tid='f'*64;record=dict(material_id=0,**{role+'_texture':None for role in ('base_color','roughness','metallic','normal')})
  original=current_material_bindings(record);binding=dict(texture_id=tid,channel='rgb',color_space='sRGB',wrap_u='repeat')
  latest=dict(record,base_color_texture=binding)
  self.assertEqual(material_conflicts({'0':original},{'0':{'roughness'}},[latest]),{})
  changed=dict(latest,roughness_texture=dict(texture_id=tid,channel='g',color_space='linear',wrap_u='repeat'))
  self.assertEqual(material_conflicts({'0':original},{'0':{'roughness'}},[changed]),{'0':{'roughness'}})
  partial=material_edit_body(0,{'roughness':dict(mode='texture',texture_id=tid,channel='g',color_space='linear',wrap='repeat')})
  self.assertEqual(set(partial['bindings']['0']),{'roughness'})
if __name__=='__main__':unittest.main()
