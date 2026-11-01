import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin"))
from substance_physics_scatter.core import Jobs, atomic_json, digest, key, png_header, VERSION
from protocol_fixture import synthetic_current
WORKER = ROOT / "build/Release/scatter_worker.exe"

class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_한글 ")
        self.root=Path(self.temp.name)
        self.sim={"count":1,"scale":1,"width":2,"depth":2,"seconds":8,"edges":"walls","seed":17}
        self.bake={"resolution":64,"height_min":0,"height_max":2,"normal":"OpenGL","samples":1}
        self.mesh=ROOT / "tests/fixtures/cube.obj"

    def tearDown(self):self.temp.cleanup()

    def run_job(self,manager,*,rebake=False):
        path=manager.prepare(self.mesh,self.sim,self.bake,rebake=rebake)
        process=subprocess.run([str(WORKER),str(path)],capture_output=True,encoding="utf-8",timeout=90)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        events=[json.loads(line) for line in process.stdout.splitlines()]
        done=events[-1];self.assertEqual(done["event"],"completed")
        return manager.validate(done["result_path"],done["job_id"])

    def test_physics_cache_and_unicode(self):
        jobs=Jobs(self.root);c=self.run_job(jobs)
        result=c["result"];self.assertEqual(result["engine"],"Jolt 5.2.0")
        self.assertEqual(result["settling_status"],"settled")
        p=result["poses"][0]["position"]
        self.assertLess(p[2],result["initial_positions"][0][2]-.2)
        self.assertGreater(p[2],.49)
        jobs.promote(c)
        before=copy.deepcopy(result["poses"])
        self.bake["resolution"]=128;c2=self.run_job(jobs,rebake=True)
        for actual,expected in zip(c2["result"]["poses"],before):
            self.assertEqual(actual["position"],expected["position"])
            for a,e in zip(actual["rotation"],expected["rotation"]):self.assertAlmostEqual(a,e,places=12)
        self.assertEqual(c2["result"]["steps"],result["steps"])
        self.assertEqual(png_header(c2["files"]["height"]),(128,128,16,0))

    def fixture_bake(self,mesh,normal="OpenGL",res=64):
        self.mesh=mesh;self.bake["normal"]=normal;self.bake["resolution"]=res
        jobs=Jobs(self.root/str(len(list(self.root.iterdir()))));path=jobs.prepare(self.mesh,self.sim,self.bake)
        request=json.loads(path.read_text());synthetic_current(jobs,path,[{"id":0,"asset_id":request["assets"][0]["asset_id"],"position":[0,0,0],"rotation":[0,0,0,1],"scale":1}])
        path=jobs.prepare(self.mesh,self.sim,self.bake,rebake=True);request=jobs.active
        process=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=90)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        return jobs.validate(path.parent/"result.json",request["job_id"])

    def test_known_height_normal_coverage(self):
        c=self.fixture_bake(self.mesh)
        h=Image.open(c["files"]["height"]);n=Image.open(c["files"]["normal"]);mask=Image.open(c["files"]["coverage"])
        self.assertLessEqual(abs(h.getpixel((32,32))-round(.5/2*65535)),1)
        self.assertEqual(n.getpixel((32,32)),(128,128,255))
        self.assertEqual(mask.getpixel((32,32)),255);self.assertEqual(mask.getpixel((0,0)),0)
        self.assertEqual(png_header(c["files"]["height"]),(64,64,16,0))
        self.assertTrue(any(h.getpixel((x,32))%257!=0 for x in range(64)))

    def test_slope_dxgl_and_2048(self):
        ogl=self.fixture_bake(ROOT/"tests/fixtures/slope.obj")
        dx=self.fixture_bake(ROOT/"tests/fixtures/slope.obj","DirectX")
        a=Image.open(ogl["files"]["normal"]).getpixel((32,32));b=Image.open(dx["files"]["normal"]).getpixel((32,32))
        self.assertEqual(a[0],b[0]);self.assertEqual(a[2],b[2]);self.assertEqual(a[1]+b[1],255)
        c=self.fixture_bake(self.mesh,res=2048);self.assertEqual(png_header(c["files"]["height"]),(2048,2048,16,0))

    def test_invalid_and_preservation(self):
        jobs=Jobs(self.root);c=self.run_job(jobs);jobs.promote(c);before=digest(self.root/"current.json")
        path=jobs.prepare(self.mesh,self.sim,self.bake);request=jobs.active.copy();jobs.cancel()
        with self.assertRaises(ValueError):jobs.validate(c["result_path"],request["job_id"])
        self.assertEqual(digest(self.root/"current.json"),before)
        path=jobs.prepare(self.mesh,self.sim,self.bake);request=jobs.active.copy()
        output=Path(request["output_directory"])
        shutil.copy(c["result_path"],output/"result.json")
        with self.assertRaises((ValueError,OSError)):jobs.validate(output/"result.json",request["job_id"])
        data=copy.deepcopy(c["result"]);data["job_id"]=request["job_id"]
        for channel in ("height","normal","coverage"):
            shutil.copy(c["files"][channel],output/(channel+".png"))
        atomic_json(output/"result.json",data)
        image=output/"height.png";image.write_bytes(image.read_bytes()[:33])
        with self.assertRaises(ValueError):jobs.validate(output/"result.json",request["job_id"])
        self.assertEqual(digest(self.root/"current.json"),before)
        bad=self.root/"bad.obj";bad.write_text("v nan 0 0\nf 1 2 3\n")
        req=json.loads(path.read_text());req["assets"][0]["path"]=str(bad);atomic_json(path,req)
        process=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True)
        self.assertNotEqual(process.returncode,0)
        self.assertEqual(digest(self.root/"current.json"),before)

    def test_no_false_periodic_claim(self):
        jobs=Jobs(self.root);self.sim["edges"]="tileable"
        with self.assertRaisesRegex(ValueError,"periodic physics is not implemented"):jobs.prepare(self.mesh,self.sim,self.bake)

    def test_reproducible_and_killed_worker(self):
        first=Jobs(self.root/"first");a=self.run_job(first);first.promote(a)
        second=Jobs(self.root/"second");b=self.run_job(second)
        self.assertEqual(a["result"]["poses"],b["result"]["poses"])
        self.assertEqual(a["hashes"],b["hashes"])
        before=digest(first.directory/"current.json")
        self.sim["count"]=500;self.sim["scale"]=.08;self.sim["seconds"]=120
        path=first.prepare(self.mesh,self.sim,self.bake)
        process=subprocess.Popen([str(WORKER),str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        process.kill();process.communicate(timeout=15);first.cancel()
        self.assertNotEqual(process.returncode,0)
        self.assertEqual(digest(first.directory/"current.json"),before)

    def test_move_and_input_identity(self):
        jobs=Jobs(self.root/"original");c=self.run_job(jobs);jobs.promote(c)
        copied=self.root/"copied";shutil.copytree(jobs.directory,copied)
        moved=Jobs(copied);current=moved.current
        self.assertTrue(Path(current["result_path"]).is_relative_to(copied))
        self.mesh=Path(current["request"]["assets"][0]["path"])
        self.bake["resolution"]=128
        rebaked=self.run_job(moved,rebake=True)
        self.assertEqual(rebaked["result"]["poses"][0]["position"],c["result"]["poses"][0]["position"])
        moved.promote(rebaked)
        request=moved.prepare(self.mesh,self.sim,self.bake)
        Path(moved.active["assets"][0]["path"]).write_text("corrupt")
        with self.assertRaises(ValueError):moved.validate(c["result_path"],moved.active["job_id"])

if __name__=="__main__":unittest.main(verbosity=2)
