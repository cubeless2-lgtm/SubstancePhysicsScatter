"""2A production-path selection, actual multi-mesh bake, identity and budget contracts."""
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.core import Jobs,VERSION,LEGACY_REBAKE,atomic_json,digest,validate_poses
from protocol_fixture import synthetic_current
WORKER=ROOT/"build/Release/scatter_worker.exe"
# These fixed UUIDs have local aliases a/b/c/d; names are not asset identity.
A,B,C,D=["0000000000004000800000000000000"+str(i) for i in (1,2,3,4)]

class Stage2(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_v2_이동 ")
        self.root=Path(self.temp.name)
        self.rows=[dict(asset_id=A,path=str(ROOT/"tests/fixtures/cube.obj"),format="obj",weight=1,scale=.25),
                   dict(asset_id=B,path=str(ROOT/"tests/fixtures/pyramid.obj"),format="obj",weight=1,scale=.25)]
        self.sim=dict(count=20,width=3,depth=3,seconds=8,seed=123456789,edges="walls")
        self.bake=dict(resolution=128,height_min=0,height_max=1,normal="OpenGL",samples=1)
    def tearDown(self):self.temp.cleanup()
    def execute(self,path,success=True):
        p=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=90)
        if success:self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        else:self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]
    def probe(self,request,success=True):
        path=self.root/"probe.json";atomic_json(path,dict(schema_version=2,job_id="probe",**request))
        return self.execute(path,success)[-1]
    def generate(self,jobs,rows=None,rebake=False):
        path=jobs.prepare(rows or self.rows,self.sim,self.bake,rebake=rebake);self.execute(path)
        return jobs.validate(path.parent/"result.json",jobs.active["job_id"])
    def fixture(self,poses,rows=None,bake=None):
        self.sim["count"]=len(poses)
        jobs=Jobs(self.root/str(len(list(self.root.iterdir()))));path=jobs.prepare(rows or self.rows,self.sim,bake or self.bake)
        cache=synthetic_current(jobs,path,poses)
        path=jobs.prepare(rows or self.rows,self.sim,bake or self.bake,rebake=True)
        return jobs,path,cache

    def test_weight_selector_distribution_repeat_reorder_and_boundaries(self):
        rows=[dict(asset_id=identity,weight=weight) for identity,weight in zip((A,B,C,D),(1,3,6,0))]
        request=dict(operation="selection_probe",assets=rows,seed=123456789,count=100000,
                     targets=[0,1/6,1/6+.5,math.nextafter(1/6+.5+1,0)])
        first=self.probe(request)
        self.assertEqual(first["targets"],[A,B,C,C])
        for identity,expected in zip((A,B,C,D),(10000,30000,60000,0)):
            actual=first["selections"].count(identity)
            self.assertLessEqual(abs(actual-expected),1000)
            if identity==D:self.assertEqual(actual,0)
        self.assertEqual(first,self.probe(request))
        request["assets"]=list(reversed(rows));self.assertEqual(first,self.probe(request))
        request.update(assets=[dict(asset_id=A,weight=1e308),dict(asset_id=B,weight=1e308)],targets=[0,1,math.nextafter(2,0)])
        self.assertEqual(self.probe(request)["targets"],[A,B,B])
        for weights in ((1e-308,1e308),(1e308,1),(0,0)):
            request.update(assets=[dict(asset_id=A,weight=weights[0]),dict(asset_id=B,weight=weights[1])],targets=[])
            self.assertEqual(self.probe(request,False)["event"],"error")

    def test_windows_sha_known_vectors_and_hashlib(self):
        values=["","abc","abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq","한글"*10000,"a"*100000]
        known=["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
               "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"]
        for i,text in enumerate(values):
            actual=self.probe(dict(operation="hash_probe",text=text))["sha256"]
            self.assertEqual(actual,hashlib.sha256(text.encode()).hexdigest())
            if i<3:self.assertEqual(actual,known[i])

    def test_mixed_physics_seed_reorder_zero_weight_and_scaled_collision(self):
        first=Jobs(self.root/"first");a=self.generate(first);first.promote(a)
        self.assertEqual({p["asset_id"] for p in a["result"]["poses"]},{A,B})
        self.assertTrue(all(p["scale"]==.25 for p in a["result"]["poses"]))
        b=self.generate(Jobs(self.root/"second"),list(reversed(self.rows)))
        self.assertEqual(a["result"]["poses"],b["result"]["poses"]);self.assertEqual(a["hashes"],b["hashes"])
        self.rows[1]["weight"]=0;c=self.generate(Jobs(self.root/"zero"))
        self.assertEqual({p["asset_id"] for p in c["result"]["poses"]},{A})
        self.sim["count"]=1;d=self.generate(Jobs(self.root/"scale"))
        p=d["result"]["poses"][0];self.assertLess(p["position"][2],.23);self.assertGreater(p["position"][2],.12)
        # Exact mesh vertex bounds transformed with the final quaternion agree with collision floor contact.
        x,y,z,w=p["rotation"]
        zs=[]
        for vx in (-.125,.125):
            for vy in (-.125,.125):
                for vz in (-.125,.125):zs.append(p["position"][2]+2*(x*z-w*y)*vx+2*(y*z+w*x)*vy+(1-2*(x*x+y*y))*vz)
        self.assertLess(abs(min(zs)),.015)

    def test_true_mesh_mixed_bake_scale_bounds_and_rebake(self):
        poses=[dict(id=0,asset_id=A,position=[-.5,0,.125],rotation=[0,0,0,1],scale=.25),
               dict(id=1,asset_id=B,position=[.5,0,0],rotation=[0,0,0,1],scale=.25)]
        jobs,path,_=self.fixture(poses);self.execute(path);c=jobs.validate(path.parent/"result.json",jobs.active["job_id"]);jobs.promote(c)
        image=Image.open(c["files"]["height"]);normal=Image.open(c["files"]["normal"]);coverage=Image.open(c["files"]["coverage"])
        cube=(42,64);pyramid=(85,64)
        self.assertLessEqual(abs(image.getpixel(cube)-round(.25*65535)),1)
        self.assertGreater(image.getpixel(pyramid),round(.20*65535))
        self.assertEqual(normal.getpixel(cube),(128,128,255));self.assertNotEqual(normal.getpixel(pyramid),(128,128,255))
        self.assertEqual(coverage.getpixel((35,64)),0);self.assertEqual(coverage.getpixel(cube),255)
        self.bake.update(resolution=256,normal="DirectX");rebaked=self.generate(jobs,rebake=True)
        self.assertEqual(rebaked["result"]["poses"],poses)
        larger=Image.open(rebaked["files"]["height"]);self.assertLessEqual(abs(larger.getpixel((85,128))-round(.25*65535)),1)

    def test_pose_validation_hash_tamper_and_allocation_preflight(self):
        good=dict(id=0,asset_id=A,position=[0,0,0],rotation=[0,0,0,1],scale=.25)
        invalid=[[good,good], [dict(good,asset_id=D)], [dict(good,position=[0,0])],
                 [dict(good,rotation=[0,0,0,0])],[dict(good,rotation=[0,0,0,1.01])],[dict(good,scale=101)], [dict(good,scale=0)]]
        for poses in invalid:
            with self.assertRaises(ValueError):self.fixture(poses)
            jobs,path,_=self.fixture([good]);bundle_path=path.parent/"pose_source.json"
            bundle=json.loads(bundle_path.read_text(encoding="utf-8"));bundle["poses"]=poses;atomic_json(bundle_path,bundle)
            jobs.active["pose_source_hash"]=digest(bundle_path);atomic_json(path,jobs.active);self.execute(path,False)
            with self.assertRaises(ValueError):validate_poses(copy.deepcopy(poses),jobs.active["assets"])
        normalized=[dict(good,rotation=[0,0,0,1.0001])];jobs,path,_=self.fixture(normalized);self.execute(path)
        self.assertEqual(json.loads((path.parent/"result.json").read_text(encoding="utf-8"))["poses"][0]["rotation"],[0,0,0,1.0001])
        jobs=Jobs(self.root/"tamper");path=jobs.prepare(self.rows,self.sim,self.bake)
        Path(jobs.active["assets"][0]["path"]).write_bytes(b"tampered")
        events=self.execute(path,False);self.assertIn("SHA256 mismatch",events[-1]["message"]);self.assertFalse(any(e.get("stage")=="physics_init" for e in events))
        # 5000 * 500 triangles >2m; no Jolt world/body event may precede refusal.
        large=self.root/"many.obj";large.write_text((ROOT/"tests/fixtures/cube.obj").read_text()+"\nf 1 2 3\n"*500,encoding="utf-8")
        rows=[dict(self.rows[0],path=str(large))];sim=dict(self.sim,count=5000)
        jobs=Jobs(self.root/"budget");path=jobs.prepare(rows,sim,self.bake);events=self.execute(path,False)
        self.assertIn("before allocation",events[-1]["message"]);self.assertFalse(any(e.get("stage")=="physics_init" for e in events))
        jobs=Jobs(self.root/"bufferbudget");path=jobs.prepare(self.rows,self.sim,dict(self.bake,resolution=8192))
        # Buffer+triangle work is <512MiB for tiny meshes; 5 *120k triangles and 8192 bake exceeds it.
        dense=self.root/"dense.obj";dense.write_text((ROOT/"tests/fixtures/cube.obj").read_text()+"\nf 1 2 3\n"*120000,encoding="utf-8")
        path=jobs.prepare([dict(self.rows[0],path=str(dense))],dict(self.sim,count=5),dict(self.bake,resolution=8192))
        events=self.execute(path,False);self.assertIn("512 MiB",events[-1]["message"]);self.assertFalse(any(e.get("stage")=="physics_init" for e in events))

    def test_v1_display_rebake_preflight_and_new_failure_preserves_pointer(self):
        jobs=Jobs(self.root/"legacy");request=dict(schema_version=1,input_hash="a"*64,asset_path="missing.obj")
        legacy=dict(job_id="00000000000000000000000000000001",request=request,files={},result_path="old",simulation_key="old")
        atomic_json(jobs.directory/"current.json",legacy);before=digest(jobs.directory/"current.json")
        self.assertEqual(jobs.current["request"]["schema_version"],1)
        with self.assertRaises(ValueError) as caught:jobs.prepare(self.rows,self.sim,self.bake,rebake=True)
        self.assertEqual(str(caught.exception),LEGACY_REBAKE)
        self.assertFalse((jobs.directory/"runs").exists());self.assertIsNone(jobs.active)
        jobs.prepare(self.rows,self.sim,self.bake);jobs.cancel();self.assertEqual(digest(jobs.directory/"current.json"),before)
        candidate=self.generate(jobs);jobs.promote(candidate);self.assertEqual(jobs.current["request"]["schema_version"],2)

    def test_all_cache_move_restore_no_originals_and_changed_assets_require_sim(self):
        source=self.root/"originals";source.mkdir()
        for index,row in enumerate(self.rows):
            path=source/(str(index)+".obj");shutil.copyfile(row["path"],path);row["path"]=str(path)
        jobs=Jobs(self.root/"project");c=self.generate(jobs);jobs.promote(c)
        moved=self.root/"moved";shutil.copytree(jobs.directory,moved);shutil.rmtree(source)
        manager=Jobs(moved);rows=manager.current["request"]["assets"]
        self.assertTrue(all(Path(row["path"]).is_relative_to(moved) for row in rows))
        self.bake["resolution"]=256;r=self.generate(manager,rows,True);self.assertEqual(r["result"]["poses"],c["result"]["poses"])
        for field in ("scale","weight"):
            changed=copy.deepcopy(rows);changed[0][field]*=2
            count=len(list((moved/"runs").iterdir()))
            with self.assertRaisesRegex(ValueError,"Physics settings changed"):manager.prepare(changed,self.sim,self.bake,rebake=True)
            self.assertEqual(len(list((moved/"runs").iterdir())),count)
        # Config can retain vanished source paths; hashes recover every owned asset cache.
        missing=[dict(row,path=str(source/(str(index)+".obj"))) for index,row in enumerate(rows)]
        r2=self.generate(manager,missing,True);self.assertEqual(r2["result"]["poses"],c["result"]["poses"])
        modified=self.root/"changed.obj";modified.write_bytes(Path(rows[0]["path"]).read_bytes()+b"\n# actual content changed\n")
        changed=copy.deepcopy(rows);changed[0]["path"]=str(modified)
        with self.assertRaisesRegex(ValueError,"Physics settings changed"):manager.prepare(changed,self.sim,self.bake,rebake=True)

    def test_input_validation_same_file_distinct_assets(self):
        jobs=Jobs(self.root/"inputs")
        for field,value in (("weight",-1),("weight",float("inf")),("scale",0),("scale",101),("asset_id","ABC"),("format","fbx")):
            rows=copy.deepcopy(self.rows);rows[0][field]=value
            with self.assertRaises(ValueError):jobs.prepare(rows,self.sim,self.bake)
        duplicate=[self.rows[0],dict(self.rows[0])]
        with self.assertRaises(ValueError):jobs.prepare(duplicate,self.sim,self.bake)
        rows=[self.rows[0],dict(self.rows[0],asset_id=B,scale=.5,weight=3)]
        jobs.prepare(rows,self.sim,self.bake)
        self.assertEqual(jobs.active["assets"][0]["content_hash"],jobs.active["assets"][1]["content_hash"])
        self.assertNotEqual(jobs.active["assets"][0]["asset_id"],jobs.active["assets"][1]["asset_id"])

    def test_input_byte_budgets_before_copy_or_parse(self):
        large=self.root/"large.obj"
        with large.open("wb") as stream:stream.truncate(257*1024*1024)
        rows=[dict(self.rows[0],path=str(large))]
        jobs=Jobs(self.root/"inputbudget")
        with self.assertRaisesRegex(ValueError,"byte budget"):jobs.prepare(rows,self.sim,self.bake)
        self.assertFalse((jobs.directory/"assets").exists())
        request=dict(schema_version=2,job_id="budget",operation="simulate_bake",simulation=self.sim,bake=self.bake,output_directory=str(self.root/"out"),assets=[dict(rows[0],content_hash="0"*64)])
        path=self.root/"budget.json";atomic_json(path,request)
        self.assertIn("byte budget",self.execute(path,False)[-1]["message"])
        with large.open("wb") as stream:stream.truncate(180*1024*1024)
        request["assets"]=[dict(request["assets"][0],asset_id=identity) for identity in (A,B,C)]
        atomic_json(path,request)
        self.assertIn("byte budget",self.execute(path,False)[-1]["message"])
        with self.assertRaisesRegex(ValueError,"byte budget"):jobs.prepare(request["assets"],self.sim,self.bake)

    def test_host_rejects_invalid_result_poses_and_keeps_current(self):
        jobs=Jobs(self.root/"result_validation");c=self.generate(jobs);jobs.promote(c)
        before=digest(jobs.directory/"current.json")
        path=jobs.prepare(self.rows,self.sim,self.bake);self.execute(path)
        result_path=path.parent/"result.json";data=json.loads(result_path.read_text(encoding="utf-8"))
        for change in (dict(asset_id=D),dict(scale=0),dict(rotation=[0,0,0,0]),dict(position=[0,0])):
            modified=copy.deepcopy(data);modified["poses"][0].update(change);atomic_json(result_path,modified)
            with self.assertRaises(ValueError):jobs.validate(result_path,jobs.active["job_id"])
            self.assertEqual(digest(jobs.directory/"current.json"),before)
        modified=copy.deepcopy(data);modified["poses"][1]["id"]=modified["poses"][0]["id"];atomic_json(result_path,modified)
        with self.assertRaises(ValueError):jobs.validate(result_path,jobs.active["job_id"])

if __name__=="__main__":unittest.main(verbosity=2)
