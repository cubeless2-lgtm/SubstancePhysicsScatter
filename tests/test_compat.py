import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter import compat
from substance_physics_scatter.core import Jobs,VERSION,atomic_json,digest
from protocol_fixture import synthetic_current
from png_pixels import signature
WORKER=ROOT/"build/Release/scatter_worker.exe"

class Compatibility(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_compat_이동 ");self.root=Path(self.temp.name)
        self.sim=dict(count=2,width=2,depth=2,seconds=8,seed=4294967295,edges="walls")
        self.bake=dict(resolution=64,height_min=0,height_max=2,normal="OpenGL",samples=1)
        self.mesh=ROOT/"tests/fixtures/cube.obj"
    def tearDown(self):self.temp.cleanup()
    def execute(self,path,success=True):
        p=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=90)
        self.assertEqual(p.returncode==0,success,str(p.returncode)+"\n"+p.stdout+p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]
    def run_job(self,jobs,rows=None,sim=None,bake=None,rebake=False):
        path=jobs.prepare(rows or self.mesh,sim or self.sim,bake or self.bake,rebake=rebake);self.execute(path)
        candidate=jobs.validate(path.parent/"result.json",jobs.active["job_id"]);jobs.promote(candidate);return candidate
    def archived_jobs(self):
        fixture=ROOT/"accepted-stage2A/fixtures";destination=self.root/"archived_copy";shutil.copytree(fixture,destination)
        cache=destination/"PhysicsScatterDemo_PhysicsScatter"
        return [Jobs(path) for path in sorted(cache.iterdir()) if path.is_dir()]
    def legacy_fixture(self,count,padding=0):
        base=next(j for j in self.archived_jobs() if j.current["request"]["operation"]=="simulate_bake")
        current=base.current;run=Path(current["result_path"]).parent
        request_template=json.loads((run/"request.json").read_bytes());result_template=json.loads((run/"result.json").read_bytes())
        jobs=Jobs(self.root/("chain_"+str(count)+"_"+str(padding)));shutil.copytree(base.directory/"assets",jobs.directory/"assets")
        first_request=first_result=None
        for index in range(count):
            identity=f"{index+1:032x}";directory=jobs.directory/"runs"/identity;directory.mkdir(parents=True)
            request=copy.deepcopy(request_template);result=copy.deepcopy(result_template)
            request.update(job_id=identity,output_directory=str(directory),operation="bake" if index+1<count else "simulate_bake")
            if index+1<count:request["poses_path"]=str(jobs.directory/"runs"/f"{index+2:032x}"/"result.json")
            result["job_id"]=identity
            if padding:request["padding"]="x"*padding;result["padding"]="y"*padding
            atomic_json(directory/"request.json",request);atomic_json(directory/"result.json",result)
            if index==0:first_request,first_result=request,result
        pointer=dict(current,job_id=f"{1:032x}",request=first_request,result=first_result)
        atomic_json(jobs.directory/"current.json",pointer)
        shutil.rmtree(self.root/"archived_copy")
        return jobs
    def test_archived_sim_and_bake_current_two_rebakes_exact_pixels_and_origin(self):
        operations=[]
        for jobs in self.archived_jobs():
            before=jobs.current;operations.append(before["request"]["operation"])
            raw_before={str(p):digest(p) for p in jobs.directory.rglob("*.json")}
            poses=copy.deepcopy(before["result"]["poses"]);expected={ch:signature(path) for ch,path in before["files"].items()}
            rows=before["request"]["assets"];sim=before["request"]["simulation"];bake=before["request"]["bake"]
            first=self.run_job(jobs,rows,sim,bake,True);second=self.run_job(jobs,rows,sim,bake,True)
            self.assertGreater(max(len(str(p)) for p in Path(first["result_path"]).parent.rglob("*.json")),260,"Regression must exercise real long provenance paths")
            for c in (first,second):
                self.assertEqual(c["result"]["poses"],poses);self.assertEqual(c["result"]["execution"],dict(physics_executed=False,body_count=0,steps=0))
                self.assertEqual(c["result"]["worker_version"],VERSION);self.assertEqual(c["simulation_key"],before["simulation_key"])
                self.assertEqual({ch:signature(path) for ch,path in c["files"].items()},expected)
                self.assertEqual(c["result"]["pose_origin"]["worker_version"],"0.2.0")
            self.assertEqual(first["result"]["pose_origin"],second["result"]["pose_origin"])
            self.assertEqual(first["result"]["rebake_source"]["job_id"],before["job_id"])
            self.assertEqual(second["result"]["rebake_source"]["job_id"],first["job_id"])
            self.assertNotEqual(first["result"]["pose_origin"]["job_id"],first["job_id"])
            self.assertEqual({p:digest(p) for p in raw_before if Path(p).name!="current.json"},{p:s for p,s in raw_before.items() if Path(p).name!="current.json"})
        self.assertEqual(set(operations),{"simulate_bake","bake"})
    def test_new_sim_two_rebakes_origin_and_immutable_move(self):
        jobs=Jobs(self.root/"new");first=self.run_job(jobs);second=self.run_job(jobs,rebake=True);third=self.run_job(jobs,rebake=True)
        for c in (second,third):
            self.assertEqual(c["result"]["poses"],first["result"]["poses"]);self.assertEqual(c["result"]["pose_origin"],first["result"]["pose_origin"])
            self.assertEqual(c["hashes"],first["hashes"]);self.assertEqual(c["result"]["execution"]["steps"],0)
        copied=self.root/"relocated";shutil.copytree(jobs.directory,copied)
        frozen={str(p.relative_to(copied)):digest(p) for p in copied.rglob("*.json") if p.name!="current.json"}
        moved=Jobs(copied);c=self.run_job(moved,rebake=True)
        self.assertEqual(c["result"]["poses"],first["result"]["poses"])
        self.assertTrue(all(digest(copied/p)==s for p,s in frozen.items()))
    def test_deep_cache_root_over_260_unicode_sim_and_rebake(self):
        directory=self.root
        while len(str(directory))<=270:directory=directory/("한글_cache_"+"x"*20)
        jobs=Jobs(directory);first=self.run_job(jobs);second=self.run_job(jobs,rebake=True)
        self.assertGreater(len(second["result_path"]),300);self.assertEqual(first["result"]["poses"],second["result"]["poses"])
        self.assertEqual(first["hashes"],second["hashes"])
    def test_non_unit_raw_quaternion_and_synthetic_physics_contract(self):
        jobs=Jobs(self.root/"synthetic");self.sim["count"]=1;path=jobs.prepare(self.mesh,self.sim,self.bake)
        poses=[dict(id=0,asset_id=jobs.active["assets"][0]["asset_id"],position=[0,0,.5],rotation=[0,0,0,1.0001],scale=1)]
        source=synthetic_current(jobs,path,poses,physics_contract=7);before=digest(source)
        c=self.run_job(jobs,rebake=True);self.assertEqual(c["result"]["poses"],poses)
        self.assertEqual(c["result"]["pose_origin"]["physics_contract_version"],7);self.assertEqual(c["result"]["physics_contract_version"],compat.VERSIONS["physics_contract_version"])
        self.assertEqual(digest(source),before)
    def test_supported_input_json_bytes_are_reused_without_reserializing(self):
        jobs=Jobs(self.root/"input_bytes");self.sim["count"]=1;path=jobs.prepare(self.mesh,self.sim,self.bake)
        physical=path.parent/"physics_inputs.json";decoded=json.loads(physical.read_bytes())
        physical.write_bytes(json.dumps(decoded,separators=(",",":"),sort_keys=False).encode())
        request=jobs.active;request["physics_input_hash"]=digest(physical);atomic_json(path,request)
        poses=[dict(id=0,asset_id=request["assets"][0]["asset_id"],position=[0,0,.5],rotation=[0,0,0,1],scale=.3)]
        synthetic_current(jobs,path,poses)
        c=self.run_job(jobs,rebake=True)
        self.assertEqual(c["request"]["physics_input_hash"],digest(physical))
        self.assertEqual((Path(c["result_path"]).parent/"physics_inputs.json").read_bytes(),physical.read_bytes())
    def test_normalization_semantic_identity_and_invalid_numbers(self):
        defaults=compat.simulation({});self.assertEqual(defaults,compat.DEFAULTS)
        for field,value in (("count",True),("count",1.),("seed",False),("seed",-1),("seed",4294967296),("width",float("inf")),("extra",1),("scale",1)):
            with self.assertRaises(ValueError):compat.simulation({field:value})
        jobs=Jobs(self.root/"identity");c=self.run_job(jobs);rows=c["request"]["assets"]
        renamed=self.root/"different_name.obj";shutil.copyfile(rows[0]["path"],renamed);rows=copy.deepcopy(rows);rows[0]["path"]=str(renamed);rows[0]["source_name"]="display only"
        d=self.run_job(jobs,list(reversed(rows)),dict(c["request"]["simulation"],width=2.),rebake=True)
        self.assertEqual(d["result"]["pose_origin"],c["result"]["pose_origin"])
        for field in ("scale","weight"):
            changed=copy.deepcopy(rows);changed[0][field]*=2
            with self.assertRaises(ValueError):jobs.prepare(changed,self.sim,self.bake,rebake=True)
        with self.assertRaises(ValueError):jobs.prepare(rows,dict(self.sim,friction=.7),self.bake,rebake=True)
    def test_unknown_partial_units_missing_request_cycle_and_path_escape_preserve(self):
        # All cases use a fresh copy of accepted immutable inputs, never the archive directly.
        for change in ("partial","unknown","units","missing_request","cycle","escape"):
            jobs=next(j for j in self.archived_jobs() if j.current["request"]["operation"]=="bake")
            c=jobs.current;run=Path(c["result_path"]).parent;request_path=run/"request.json";result_path=run/"result.json"
            request=json.loads(request_path.read_text(encoding="utf-8"));result=json.loads(result_path.read_text(encoding="utf-8"))
            if change=="partial":result["pose_format_version"]=1
            elif change=="unknown":result["worker_version"]="9.9.9"
            elif change=="units":result["units"]="centimeters"
            elif change=="missing_request":request_path.unlink()
            elif change=="cycle":request["poses_path"]=request["output_directory"]+"/result.json"
            elif change=="escape":request["poses_path"]=str(run/".."/".."/"outside.json")
            if change!="missing_request":atomic_json(request_path,request)
            atomic_json(result_path,result);pointer=digest(jobs.directory/"current.json");count=len(list((jobs.directory/"runs").iterdir()))
            with self.assertRaises(ValueError):jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
            self.assertEqual(digest(jobs.directory/"current.json"),pointer);self.assertEqual(count,len(list((jobs.directory/"runs").iterdir())))
            shutil.rmtree(self.root/"archived_copy")
    def test_raw_byte_tamper_native_semantics_and_provenance_budgets(self):
        jobs=Jobs(self.root/"tamper");self.run_job(jobs)
        path=jobs.prepare(self.mesh,self.sim,self.bake,rebake=True)
        physical=path.parent/"physics_inputs.json";physical.write_bytes(physical.read_bytes()+b" ")
        self.assertIn("SHA mismatch",self.execute(path,False)[-1]["message"])
        path=jobs.prepare(self.mesh,self.sim,self.bake,rebake=True);request=jobs.active
        physical=path.parent/"physics_inputs.json";data=json.loads(physical.read_bytes());data["simulation"]["friction"]=.8
        atomic_json(physical,data);request["physics_input_hash"]=digest(physical);atomic_json(path,request)
        self.assertIn("semantics",self.execute(path,False)[-1]["message"])
        big=self.root/"oversize.json"
        with big.open("wb") as stream:stream.truncate(16*1024*1024+1)
        with self.assertRaisesRegex(ValueError,"16 MiB"):compat.Blobs().read(big)
        blobs=compat.Blobs();blobs.add(b'{}')
        with mock.patch.object(compat,"TOTAL",2):
            blobs.add(b'{}')
            with self.assertRaisesRegex(ValueError,"128 MiB"):blobs.add(b'{"x":1}')
        self.assertEqual(len(blobs.data),1)
    def test_legacy_chain_64_boundary_and_65_preflight(self):
        for count in (64,65):
            jobs=self.legacy_fixture(count);c=jobs.current
            if count==65:
                with self.assertRaisesRegex(ValueError,"long legacy chain"):jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
                self.assertEqual(len(list((jobs.directory/"runs").iterdir())),65)
            else:
                path=jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True);self.execute(path)
                result=jobs.validate(path.parent/"result.json",jobs.active["job_id"])
                self.assertEqual(result["result"]["pose_origin"]["job_id"],f"{64:032x}")
    def test_real_total_budget_host_and_worker_before_bake(self):
        jobs=self.legacy_fixture(5,14*1024*1024);c=jobs.current;pointer=digest(jobs.directory/"current.json")
        with self.assertRaisesRegex(ValueError,"128 MiB"):jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
        self.assertIsNone(jobs.active);self.assertEqual(len(list((jobs.directory/"runs").iterdir())),5)
        # Test-only increased host limit constructs a valid negative fixture for the fixed native 128MiB limit.
        with mock.patch.object(compat,"TOTAL",256*1024*1024):path=jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
        events=self.execute(path,False);self.assertIn("128 MiB",events[-1]["message"])
        self.assertFalse(any(e.get("stage") in ("physics_init","pose_validated","bake") for e in events));self.assertEqual(digest(jobs.directory/"current.json"),pointer)
    def test_native_16mib_and_role_collision(self):
        jobs=next(j for j in self.archived_jobs() if j.current["request"]["operation"]=="bake");c=jobs.current
        path=jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
        pose_source=path.parent/"pose_source.json";bundle=json.loads(pose_source.read_bytes());bundle["legacy_chain"][0]["request_sha256"]=bundle["legacy_chain"][0]["result_sha256"]
        atomic_json(pose_source,bundle);request=jobs.active;request["pose_source_hash"]=digest(pose_source);atomic_json(path,request)
        self.execute(path,False)
        path=jobs.prepare(c["request"]["assets"],c["request"]["simulation"],c["request"]["bake"],rebake=True)
        pose_source=path.parent/"pose_source.json"
        with pose_source.open("ab") as stream:stream.write(b' '*(16*1024*1024+1))
        request=jobs.active;request["pose_source_hash"]=digest(pose_source);atomic_json(path,request)
        self.assertIn("16 MiB",self.execute(path,False)[-1]["message"])
    def test_owned_runtime_path_guards(self):
        jobs=Jobs(self.root/"guard");c=self.run_job(jobs);before=copy.deepcopy(c)
        bad=copy.deepcopy(before);bad["job_id"]="../outside";atomic_json(jobs.directory/"current.json",bad)
        with self.assertRaises(ValueError):_ = jobs.current
        bad=copy.deepcopy(before);bad["request"]["assets"][0]["content_hash"]="../../outside";atomic_json(jobs.directory/"current.json",bad)
        with self.assertRaises(ValueError):_ = jobs.current
        self.assertFalse((self.root/"outside").exists())
        atomic_json(jobs.directory/"current.json",before)
        self.assertEqual(jobs.current["job_id"],c["job_id"])
    def test_negative_zero_canonical_bytes_key_native_and_existing_raw_key(self):
        rows=[dict(asset_id="1"*32,content_hash="a"*64,format="obj",weight=1.,scale=.3)]
        positive=compat.encoded(compat.inputs(rows,{"friction":0.,"restitution":0.}))
        negative=compat.encoded(compat.inputs(rows,{"friction":-0.,"restitution":-0.}))
        self.assertEqual(positive,negative);self.assertEqual(compat.sha(positive),compat.sha(negative))
        self.assertEqual(compat.simulation_key(compat.sha(positive)),compat.simulation_key(compat.sha(negative)))
        sim=dict(self.sim,count=1,friction=-0.,restitution=-0.)
        jobs=Jobs(self.root/"zero");path=jobs.prepare(self.mesh,sim,self.bake);request=jobs.active
        self.assertNotIn(b'-0.0',(path.parent/"physics_inputs.json").read_bytes())
        request["simulation"].update(friction=-0.,restitution=-0.);atomic_json(path,request)
        self.execute(path);candidate=jobs.validate(path.parent/"result.json",request["job_id"]);jobs.promote(candidate)
        # An older supported record may contain raw -0 bytes. Do not rewrite its bytes/hash/key during rebake.
        old=Jobs(self.root/"old_negative_zero");path=old.prepare(self.mesh,sim,self.bake)
        physical=path.parent/"physics_inputs.json";value=json.loads(physical.read_bytes());value["simulation"].update(friction=-0.,restitution=-0.)
        physical.write_bytes(compat.encoded(value));request=old.active;request["physics_input_hash"]=digest(physical);atomic_json(path,request)
        poses=[dict(id=0,asset_id=request["assets"][0]["asset_id"],position=[0,0,.5],rotation=[0,0,0,1],scale=.3)]
        source=synthetic_current(old,path,poses);old_sha=digest(source);old_key=old.current["simulation_key"];input_bytes=physical.read_bytes()
        result=self.run_job(old,sim=sim,rebake=True)
        self.assertEqual(result["simulation_key"],old_key);self.assertEqual(digest(source),old_sha)
        self.assertEqual((Path(result["result_path"]).parent/"physics_inputs.json").read_bytes(),input_bytes)

    def test_step_body_settling_corruption_rejected_by_host_and_native(self):
        base=Jobs(self.root/"metrics_baseline");self.sim["count"]=1
        initial=self.run_job(base);rebaked=self.run_job(base,rebake=True)
        immutable={str(p.relative_to(base.directory)):digest(p) for p in base.directory.rglob("*.json") if p.name!="current.json"}
        first_steps=initial["result"]["source_steps"];self.assertGreater(first_steps,0)
        sim_cases=[{"steps":v,"execution.steps":v} for v in (-1,.5,True)]
        sim_cases += [{"steps":first_steps+1,"execution.steps":first_steps+1,"source_steps":first_steps+1}]
        sim_cases += [{"origin.steps":v} for v in (-1,.5,True,first_steps+1)]
        sim_cases += [{"execution.body_count":v} for v in (-1,1.,True,2)]
        sim_cases += [{"settling_status":v} for v in (False,"","different_status")]
        sim_cases += [{"steps":v,"source_steps":v,"execution.steps":v,"origin.steps":v} for v in (True,1.)]
        bake_cases=[{"steps":0},{"steps":first_steps+1,"source_steps":first_steps+1}]
        bake_cases += [{"execution.steps":v} for v in (-1,.5,False,1)]
        bake_cases += [{"execution.body_count":v} for v in (-1,0.,False,1)]
        bake_cases += [{"execution.physics_executed":0},{"settling_status":"different_status"}]
        for phase,candidate,cases in (("sim",initial,sim_cases),("bake",rebaked,bake_cases)):
            atomic_json(base.directory/"current.json",candidate)
            native_root=self.root/("metrics_native_"+phase);shutil.copytree(base.directory,native_root);native=Jobs(native_root)
            for index,changes in enumerate(cases):
                host_root=self.root/(phase+"_host_"+str(index));shutil.copytree(base.directory,host_root);host=Jobs(host_root);current=host.current
                raw_path=Path(current["result_path"]);data=json.loads(raw_path.read_bytes());origin_path=raw_path.parent/data["origin"]["record_path"];origin=json.loads(origin_path.read_bytes())
                origin_changed=False
                for key,value in changes.items():
                    if key.startswith("origin."):origin[key.split(".")[1]]=value;origin_changed=True
                    elif key.startswith("execution."):data["execution"][key.split(".")[1]]=value
                    else:data[key]=value
                if origin_changed:
                    atomic_json(origin_path,origin);origin_sha=digest(origin_path)
                    for reference in (data["origin"],data["pose_origin"],data["pose_envelope"]["origin"]):reference["record_sha256"]=origin_sha
                atomic_json(raw_path,data);pointer=digest(host.directory/"current.json");run_count=len(list((host.directory/"runs").iterdir()))
                host.active=current["request"]
                with self.subTest(phase=phase,index=index,side="host_validate"),self.assertRaises(ValueError):host.validate(raw_path,current["job_id"])
                host.cancel()
                with self.subTest(phase=phase,index=index,side="host_prepare"),self.assertRaises(ValueError):host.prepare(self.mesh,self.sim,self.bake,rebake=True)
                self.assertEqual(digest(host.directory/"current.json"),pointer);self.assertEqual(len(list((host.directory/"runs").iterdir())),run_count)
                # Rebuild only a negative working bundle with correct raw hashes, bypassing the host preflight.
                request_path=native.prepare(self.mesh,self.sim,self.bake,rebake=True);bundle_path=request_path.parent/"pose_source.json";bundle=json.loads(bundle_path.read_bytes())
                if origin_changed:
                    blob=request_path.parent/"provenance"/(origin_sha+".json");blob.write_bytes(origin_path.read_bytes())
                    bundle["origin"]["record_sha256"]=origin_sha
                source_bytes=compat.encoded(data);source_sha=compat.sha(source_bytes)
                (request_path.parent/"provenance"/(source_sha+".json")).write_bytes(source_bytes)
                bundle["source"]["record_sha256"]=source_sha;bundle["source_steps"]=data["source_steps"];bundle["settling_status"]=data["settling_status"]
                atomic_json(bundle_path,bundle);native.active["pose_source_hash"]=digest(bundle_path);atomic_json(request_path,native.active)
                with self.subTest(phase=phase,index=index,side="native"):
                    events=self.execute(request_path,False);self.assertFalse(any(e.get("stage")=="bake" for e in events))
            native.cancel()
        self.assertTrue(all(digest(base.directory/path)==hash_value for path,hash_value in immutable.items()))

if __name__=="__main__":unittest.main(verbosity=2)
