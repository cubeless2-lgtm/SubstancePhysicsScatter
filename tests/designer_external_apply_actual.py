"""Fixed, isolated Designer SDK HNC/PBR application and rollback smoke lane."""
from pathlib import Path
import copy,hashlib,importlib,json,sys,urllib.request,uuid
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'output/designer_bridge/external-apply-actual'/uuid.uuid4().hex
WORK.mkdir(parents=True,exist_ok=False)
REPORT=WORK/'report.json';report={'status':'FAIL','work':str(WORK)}
package=None;mgr=None
try:
 import sd
 from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
 from sd.api.sdproperty import SDPropertyCategory
 from substance_physics_scatter import designer,designer_external
 importlib.reload(designer_external)
 base='http://127.0.0.1:8765'
 def get(path,limit):
  with urllib.request.urlopen(base+path,timeout=15) as r:
   raw=r.read(limit+1)
   if len(raw)>limit:raise ValueError('Response too large')
   return raw
 state=json.loads(get('/api/state',4*1024*1024));job=state['current']['job_id']
 manifest=json.loads(get('/api/designer-handoff/'+job,1024*1024))
 if len(manifest['maps'])!=7:raise ValueError('Actual smoke requires a seven-channel viewer current')
 app=sd.getContext().getSDApplication();mgr=app.getPackageMgr();original={str(p.getUID()) for p in mgr.getUserPackages()}
 package=mgr.newUserPackage()
 if str(package.getUID()) in original or package.getFilePath():raise ValueError('Test package ownership')
 parent=SDSBSCompGraph.sNew(package);parent.setIdentifier('ExternalApplySmoke');pkg=WORK/'ExternalApplySmoke.sbs';mgr.savePackageAs(package,str(pkg))
 graph,instance=designer.create(parent);graph_id=graph.getIdentifier();instance_id=instance.getIdentifier();old=copy.deepcopy(designer.settings(graph))
 stage=designer_external.owned_stage(graph,job,designer);stage.mkdir(parents=True,exist_ok=False);files={}
 for role,row in manifest['maps'].items():
  raw=get('/api/maps/'+job+'/'+role,row['bytes'])
  if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('Map changed in transit')
  p=stage/(role+'.png');p.write_bytes(raw);files[role]=p
 if json.loads(get('/api/designer-handoff/'+job,1024*1024))!=manifest:raise ValueError('Viewer current changed')
 hnc=dict(manifest,maps={k:manifest['maps'][k] for k in designer_external.HNC});hnc_files={k:files[k] for k in designer_external.HNC}
 designer_external.apply_external(graph,hnc,hnc_files)
 assert designer.settings(graph)['current'] == old.get('current') if 'current' in old else 'current' not in designer.settings(graph)
 assert set(designer_external.connection_snapshot(graph,designer)[i][0] for i in range(3))==set(designer_external.HNC)
 designer_external.apply_external(graph,manifest,files)
 before=designer_external.connection_snapshot(graph,designer);meta=copy.deepcopy(designer.settings(graph));assert set(x[0] for x in before)==set(designer_external.HNC+designer_external.PBR)
 sys.path.insert(0,str(ROOT/'tests'))
 from png_pixels import decoded
 exported=WORK/'exported';designer.export_outputs(graph,exported);pixel_checks={}
 for role in manifest['maps']:
  ih,ip=decoded(files[role]);oh,op=decoded(exported/(role+'.png'))
  if ih[:3]!=oh[:3]:raise ValueError('Designer image dimensions/precision differ: '+role+' '+str((ih,oh)))
  ic={0:1,2:3,6:4}[ih[3]];oc={0:1,2:3,6:4}[oh[3]];step=ih[2]//8
  if ic not in (1,3,4) or oc not in (1,3,4):raise ValueError('Unsupported image layout: '+role)
  mismatches=0
  for n in range(ih[0]*ih[1]):
   for channel in range(1 if ic==1 else 3):
    ai=(n*ic+channel)*step;bi=(n*oc+(channel if oc>1 else 0))*step
    if ip[ai:ai+step]!=op[bi:bi+step]:mismatches+=1
  pixel_checks[role]=mismatches
 if any(pixel_checks.values()):raise ValueError('Designer pixel mismatch: '+str(pixel_checks))
 count=[0]
 def fail_after_compute():
  count[0]+=1
  if count[0]==3:raise ValueError('Intentional rollback probe')
 try:designer_external.apply_external(graph,manifest,files,guard=fail_after_compute)
 except ValueError as e:
  if str(e)!='Intentional rollback probe':raise
 else:raise ValueError('Rollback probe did not fail')
 assert designer_external.connection_snapshot(graph,designer)==before and designer.settings(graph)==meta
 mgr.savePackage(package);mgr.unloadUserPackage(package);package=None
 package=mgr.loadUserPackage(str(pkg));parent=next(g for g in package.getChildrenResources(True) if isinstance(g,SDSBSCompGraph) and g.getIdentifier()=='ExternalApplySmoke');graph=next(g for g in package.getChildrenResources(True) if isinstance(g,SDSBSCompGraph) and g.getIdentifier()==graph_id)
 instance=parent.getNodeFromId(instance_id);ports=[p.getId() for p in instance.getProperties(SDPropertyCategory.Output)]
 assert set(designer_external.HNC+designer_external.PBR)<=set(ports),ports
 assert designer.settings(graph)['external_current']['job_id']==job
 from substance_physics_scatter.core import Jobs
 assert designer.checked_current(graph,Jobs(designer.result_directory(graph))) is None
 report.update(status='PASS',job_id=job,graph=graph_id,parent_ports=ports,channels=list(manifest['maps']),hnc_then_pbr=True,rollback=True,save_reopen=True,reopen_checked_current=True,pixel_mismatches=pixel_checks)
except BaseException as error:
 import traceback
 report.update(error=repr(error),traceback=traceback.format_exc())
finally:
 if package is not None and mgr is not None:
  try:mgr.unloadUserPackage(package)
  except BaseException as error:report.update(status='FAIL',unload_error=repr(error))
 REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
