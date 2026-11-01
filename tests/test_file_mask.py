import copy,hashlib,json,math,shutil,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.core import Jobs,atomic_json,digest
from substance_physics_scatter import compat,maskio
from png_pixels import signature
from test_mask_decoder import png
WORKER=ROOT/"build/Release/scatter_worker.exe"

class FileMask(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_file_mask_한글 ");self.root=Path(self.temp.name)
        self.rows=[dict(asset_id="00000000000040008000000000000001",path=str(ROOT/"tests/fixtures/cube.obj"),format="obj",scale=.25,weight=1.),dict(asset_id="00000000000040008000000000000002",path=str(ROOT/"tests/fixtures/pyramid.obj"),format="obj",scale=.25,weight=1.)]
        self.sim=dict(count=20,width=2,depth=2,seconds=2,seed=123456789,edges="walls");self.bake=dict(resolution=64,height_min=0,height_max=8,normal="OpenGL",samples=1)
        self.black=self.root/"black.png";self.black.write_bytes(png(b"\0\0"))
        self.white=self.root/"white.png";self.white.write_bytes(png(b"\0\xff"))
    def tearDown(self):self.temp.cleanup()
    def execute(self,path,success=True):
        p=subprocess.run([str(WORKER),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=120)
        self.assertEqual(p.returncode==0,success,p.stdout+p.stderr)
        return [json.loads(line) for line in p.stdout.splitlines()]
    def run_job(self,jobs,mask=None,rebake=False,rows=None,sim=None,bake=None):
        path=jobs.prepare(rows or self.rows,sim or self.sim,bake or self.bake,scatter_mask=mask,rebake=rebake);events=self.execute(path)
        candidate=jobs.validate(path.parent/"result.json",jobs.active["job_id"]);jobs.promote(candidate);return candidate,events
    def placement(self,mask=None,sim=None,rows=None):
        jobs=Jobs(self.root/("placement"+str(len(list(self.root.iterdir())))))
        path=jobs.prepare(rows or self.rows,sim or self.sim,self.bake,scatter_mask=mask);request=jobs.active;request["operation"]="placement_probe";atomic_json(path,request)
        return self.execute(path)[-1]
    def test_omitted_white_rng_initial_final_and_mesh_prefix(self):
        a,_=self.run_job(Jobs(self.root/"omitted"));b,_=self.run_job(Jobs(self.root/"white"),self.white)
        self.assertEqual(a["result"]["poses"],b["result"]["poses"]);self.assertEqual(a["result"]["initial_positions"],b["result"]["initial_positions"])
        self.assertEqual(a["hashes"],b["hashes"]);self.assertNotEqual(a["simulation_key"],b["simulation_key"])
        p=self.placement();q=self.placement(self.white)
        for field in ("positions","rotations","asset_ids"):self.assertEqual(p[field],q[field])
        self.assertEqual(p["mask_draws"],0);self.assertEqual(q["mask_draws"],self.sim["count"])
        radius=p["requested_radius"]
        for i,a in enumerate(p["positions"]):
            for b in p["positions"][i+1:]:self.assertGreaterEqual(math.dist(a,b)+1e-6,2*radius)
    def test_nonempty_calculation_matches_actual_021_worker(self):
        new,_=self.run_job(Jobs(self.root/"current_engine"))
        old=Jobs(self.root/"approved_engine");path=old.prepare(self.rows,self.sim,self.bake)
        physical=compat.inputs(old.active["assets"],old.active["simulation"],version=1);raw=compat.encoded(physical)
        (path.parent/"physics_inputs.json").write_bytes(raw)
        old.active.update(worker_version="0.2.1",physics_contract_version=1,bake_contract_version=1,physics_input_format_version=1,physics_input_hash=compat.sha(raw),simulation_key=compat.simulation_key(compat.sha(raw),1))
        old.active.pop("scatter_mask");atomic_json(path,old.active)
        p=subprocess.run([str(ROOT/"accepted-stage2A1/scatter_worker.exe"),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=60)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);original=json.loads((path.parent/"result.json").read_bytes())
        for field in ("poses","initial_positions","steps","settling_status"):self.assertEqual(new["result"][field],original[field])
        for channel in ("height","normal","coverage"):self.assertEqual(signature(new["files"][channel]),signature(path.parent/(channel+".png")))
    def test_black_empty_origin_pixels_and_two_rebakes(self):
        jobs=Jobs(self.root/"black_jobs");c,events=self.run_job(jobs,self.black,bake=dict(self.bake,height_min=-2,height_max=7))
        r=c["result"];self.assertEqual(r["poses"],[]);self.assertEqual(r["initial_positions"],[]);self.assertEqual(r["attempt_count"],0)
        self.assertEqual(r["spawn_status"],"empty");self.assertEqual(r["spawn_stop_reason"],"all_black");self.assertEqual(r["settling_status"],"not_run")
        self.assertEqual(r["execution"],dict(physics_executed=False,body_count=0,steps=0));self.assertFalse(any(e.get("stage")=="physics_init" for e in events))
        self.assertEqual(set(Image.open(c["files"]["height"]).tobytes()),{0});self.assertEqual(Image.open(c["files"]["normal"]).tobytes(),b"\x80\x80\xff"*(64*64));self.assertEqual(set(Image.open(c["files"]["coverage"]).tobytes()),{0})
        origin=Path(c["result_path"]).parent/r["origin"]["record_path"];original=digest(origin)
        for _ in range(2):
            d,events=self.run_job(jobs,self.black,True,bake=dict(self.bake,height_min=-2,height_max=7))
            self.assertEqual(d["hashes"],c["hashes"]);self.assertEqual(d["result"]["pose_origin"],r["pose_origin"])
            for key in compat.SPAWN_FIELDS:self.assertEqual(d["result"][key],r[key])
            self.assertEqual(d["result"]["execution"],r["execution"]);self.assertEqual(digest(origin),original)
    def test_partial_prefix_empty_attempts_and_png8_16(self):
        sparse=self.root/"sparse.png";sparse.write_bytes(png(b"\0\xff\0\0"+b"\0\0\0\0"*2,3,3))
        sparse16=self.root/"sparse16.png";sparse16.write_bytes(png(b"\0\xff\xff\0\0\0\0"+b"\0\0\0\0\0\0\0"*2,3,3,bits=16))
        simulation=dict(self.sim,width=2.3,depth=2.3)
        baseline=self.placement(sim=simulation);a=self.placement(sparse,simulation);b=self.placement(sparse16,simulation)
        for field in ("positions","rotations","asset_ids","attempt_count","spawned_count"):self.assertEqual(a[field],b[field])
        self.assertEqual(a["spawn_status"],"partial");self.assertEqual(a["spawn_stop_reason"],"attempts_exhausted");self.assertEqual(a["attempt_count"],200)
        self.assertEqual(a["asset_ids"],baseline["asset_ids"][:a["spawned_count"]]);self.assertEqual(a["rotations"],baseline["rotations"][:a["spawned_count"]]);self.assertEqual(a["mask_draws"],200)
        c,_=self.run_job(Jobs(self.root/"partial"),sparse,sim=dict(simulation,seconds=.1))
        self.assertEqual(c["result"]["spawned_count"],a["spawned_count"])
        # One white pixel exists, but the sole grid center samples a black pixel.
        missed=self.root/"missed.png";missed.write_bytes(png(b"\0\xff\0\0",1,2))
        s=dict(self.sim,count=1,width=.6,depth=.6);d,_=self.run_job(Jobs(self.root/"missed"),missed,sim=s)
        self.assertEqual(d["result"]["spawn_stop_reason"],"attempts_exhausted");self.assertEqual(d["result"]["attempt_count"],10);self.assertEqual(d["result"]["spawned_count"],0)
    def test_height_last_attempt_priority_and_empty(self):
        missed=self.root/"missed.png";missed.write_bytes(png(b"\0\xff\0\0",1,2))
        rows=[dict(self.rows[0],scale=46/(math.sqrt(3)/2))];sim=dict(self.sim,count=1,width=92.1,depth=92.1)
        result=self.placement(missed,sim,rows);self.assertEqual(result["attempt_count"],10);self.assertEqual(result["spawn_stop_reason"],"initial_height_limit");self.assertEqual(result["mask_draws"],9)
        big=self.root/"large_valid.obj";big.write_text((ROOT/"tests/fixtures/cube.obj").read_text().replace('0.5','2.885'),encoding="utf-8")
        rows=[dict(self.rows[0],path=str(big),scale=100)];sim=dict(self.sim,count=1,width=1000,depth=1000)
        result=self.placement(None,sim,rows);self.assertEqual(result["spawn_status"],"empty");self.assertEqual(result["spawn_stop_reason"],"initial_height_limit");self.assertEqual(result["attempt_count"],1)
    def test_exact_probability_boundary_draws_and_last_accept_priority(self):
        from test_mask_decoder import MaskDecoder
        probe=MaskDecoder();probe.setUp()
        try:
            pairs=[(0,0),(4294967295,0),(0,65535),(4294967295,65535)]
            for p in (1,257,32768,65534):
                boundary=(p*4294967296+65534)//65535
                pairs.extend(((boundary-1,p),(boundary,p)))
            record=probe.probe(png(),comparisons=pairs,random_seeds=list(range(100)),random_count=10)
            self.assertEqual(record["comparisons"],[r*65535<p*4294967296 for r,p in pairs])
            for seed,sequence in enumerate(record["random"]):
                p=sequence[9]*65535//4294967296+1
                if 0<p<=65535 and all(r*65535>=p*4294967296 for r in sequence[:9]):break
            else:self.fail("No deterministic last-attempt fixture found")
            image=self.root/"last.png";image.write_bytes(png(b"\0"+struct.pack(">H",p),bits=16))
            result=self.placement(image,dict(self.sim,count=1,seed=seed))
            self.assertEqual((result["attempt_count"],result["spawned_count"],result["spawn_stop_reason"]),(10,1,"requested_count_reached"))
            for seed,sequence in enumerate(record["random"]):
                p=sequence[0]*65535//4294967296+1
                if 0<p<=65535 and all(r*65535>=p*4294967296 for r in sequence[1:9]):break
            else:self.fail("No deterministic partial-height fixture found")
            image.write_bytes(png(b"\0"+struct.pack(">H",p),bits=16))
            rows=[dict(self.rows[0],scale=46/(math.sqrt(3)/2))]
            result=self.placement(image,dict(self.sim,count=20,seed=seed,width=92.1,depth=92.1),rows)
            self.assertEqual((result["spawn_status"],result["spawn_stop_reason"],result["spawned_count"],result["attempt_count"],result["mask_draws"]),("partial","initial_height_limit",1,10,9))
        finally:probe.tearDown()
    def test_mask_move_immutable_and_format1_empty_rejected(self):
        jobs=Jobs(self.root/"movable");before,_=self.run_job(jobs,self.black)
        immutable={str(p.relative_to(jobs.directory)):digest(p) for p in jobs.directory.rglob("*.json") if p.name!="current.json"}
        moved=self.root/"new_location";shutil.copytree(jobs.directory,moved);shutil.rmtree(jobs.directory);self.black.unlink()
        jobs=Jobs(moved);current=jobs.current;mask=current["request"]["scatter_mask"]
        self.assertTrue(Path(mask["path"]).is_relative_to(moved));after,_=self.run_job(jobs,mask,True)
        self.assertEqual(after["result"]["pose_origin"],before["result"]["pose_origin"]);self.assertEqual(after["hashes"],before["hashes"])
        self.assertTrue(all(digest(moved/path)==sha for path,sha in immutable.items()))
        from protocol_fixture import synthetic_current
        fake=Jobs(self.root/"format1_empty");path=fake.prepare(self.rows[0]["path"],dict(self.sim,count=1),self.bake)
        synthetic_current(fake,path,[])
        self.assertEqual(fake.current["request"]["physics_input_format_version"],1)
        with self.assertRaises(ValueError):fake.prepare(self.rows[0]["path"],dict(self.sim,count=1),self.bake,rebake=True)
    def test_cache_change_missing_damage_and_allblack_does_not_bypass_assets(self):
        jobs=Jobs(self.root/"cache");c,_=self.run_job(jobs,self.black);pointer=digest(jobs.directory/"current.json")
        with self.assertRaises(ValueError):jobs.prepare(self.rows,self.sim,self.bake,rebake=True)
        with self.assertRaises(ValueError):jobs.prepare(self.rows,self.sim,self.bake,scatter_mask=self.white,rebake=True)
        mask=jobs.current["request"]["scatter_mask"];self.black.unlink();d,_=self.run_job(jobs,mask,True)
        io=Path(mask["path"]);io.write_bytes(b"corrupt")
        with self.assertRaises(ValueError):jobs.prepare(self.rows,self.sim,self.bake,scatter_mask=mask,rebake=True)
        self.assertEqual(jobs.current["job_id"],d["job_id"])
        # Worker validates geometry/region and the full requested triangle budget even with decoded black pixels.
        black=self.root/"other_black.png";black.write_bytes(png(b"\0\0"))
        rows=[dict(self.rows[0],scale=100)];j=Jobs(self.root/"oversized");q=j.prepare(rows,self.sim,self.bake,scatter_mask=black)
        e=self.execute(q,False);self.assertIn("too large",e[-1]["message"]);self.assertFalse(any(v.get("stage")=="physics_init" for v in e))
        invalid=self.root/"invalid.obj";invalid.write_text('bad mesh',encoding="utf-8")
        q=j.prepare([dict(self.rows[0],path=str(invalid))],self.sim,self.bake,scatter_mask=black);self.execute(q,False)
        dense=self.root/"dense.obj";dense.write_text((ROOT/"tests/fixtures/cube.obj").read_text()+"\nf 1 2 3\n"*500,encoding="utf-8")
        q=j.prepare([dict(self.rows[0],path=str(dense))],dict(self.sim,count=5000),self.bake,scatter_mask=black)
        self.assertIn("triangle budget",self.execute(q,False)[-1]["message"])
    def test_format1_021_sim_and_rebake_fixtures_unchanged(self):
        source=ROOT/"accepted-stage2A1/fixtures";copy=self.root/"approved021";shutil.copytree(source,copy)
        roots=[p for p in copy.rglob("current.json") if "migration" not in p.parts and json.loads(p.read_text(encoding="utf-8"))["request"].get("physics_input_format_version")==1]
        self.assertTrue(roots)
        for index,pointer in enumerate(roots[:2]):
            jobs=Jobs(pointer.parent);old=jobs.current;raw={str(p):digest(p) for p in jobs.directory.rglob("*.json") if p.name!="current.json"}
            new,_=self.run_job(jobs,None,True,old["request"]["assets"],old["request"]["simulation"],old["request"]["bake"])
            self.assertEqual(new["request"]["physics_input_format_version"],1);self.assertEqual(new["simulation_key"],old["simulation_key"])
            self.assertEqual(new["result"]["poses"],old["result"]["poses"]);self.assertEqual(new["result"]["pose_origin"],old["result"]["pose_origin"])
            self.assertNotIn("spawned_count",new["result"])
            self.assertEqual({ch:signature(p) for ch,p in new["files"].items()},{ch:signature(p) for ch,p in old["files"].items()})
            self.assertTrue(all(digest(path)==sha for path,sha in raw.items()))
    def test_spawn_origin_corruption_bool_positions_and_empty_pixels_preserve(self):
        jobs=Jobs(self.root/"corruption");good,_=self.run_job(jobs,self.black);pointer=digest(jobs.directory/"current.json")
        path=jobs.prepare(self.rows,self.sim,self.bake,scatter_mask=self.black,rebake=True);self.execute(path);result_path=path.parent/"result.json";record=json.loads(result_path.read_text(encoding="utf-8"))
        for changes in (dict(requested_count=True),dict(attempt_count=1),dict(spawned_count=1),dict(spawn_stop_reason="attempts_exhausted"),dict(initial_positions=[[True,0,0]]),dict(poses=None)):
            value=copy.deepcopy(record);value.update(changes);atomic_json(result_path,value)
            with self.assertRaises((ValueError,TypeError)):jobs.validate(result_path,jobs.active["job_id"])
            self.assertEqual(digest(jobs.directory/"current.json"),pointer)
        atomic_json(result_path,record);image=Image.open(path.parent/"normal.png");image.putpixel((0,0),(0,0,0));image.save(path.parent/"normal.png")
        with self.assertRaises(ValueError):jobs.validate(result_path,jobs.active["job_id"])
    def test_native_spawn_provenance_and_mask_byte_tamper_before_physics(self):
        jobs=Jobs(self.root/"native_bad");good,_=self.run_job(jobs,self.black);pointer=digest(jobs.directory/"current.json")
        cases=(dict(requested_count=True),dict(attempt_count=1),dict(spawn_stop_reason="initial_height_limit"),dict(poses=None),dict(initial_positions=[[False,0,0]]))
        for changes in cases:
            path=jobs.prepare(self.rows,self.sim,self.bake,scatter_mask=self.black,rebake=True)
            bundle_path=path.parent/"pose_source.json";bundle=json.loads(bundle_path.read_bytes())
            source=json.loads((path.parent/"provenance"/(bundle["source"]["record_sha256"]+".json")).read_bytes());source.update(changes)
            raw=compat.encoded(source);sha=compat.sha(raw);(path.parent/"provenance"/(sha+".json")).write_bytes(raw)
            bundle["source"]["record_sha256"]=sha;atomic_json(bundle_path,bundle);jobs.active["pose_source_hash"]=digest(bundle_path);atomic_json(path,jobs.active)
            events=self.execute(path,False);self.assertFalse(any(e.get("stage")=="physics_init" for e in events));self.assertEqual(digest(jobs.directory/"current.json"),pointer)
        path=jobs.prepare(self.rows,self.sim,self.bake,scatter_mask=self.black)
        cached=Path(jobs.active["scatter_mask"]["path"]);cached.write_bytes(self.white.read_bytes())
        events=self.execute(path,False);self.assertIn("SHA",events[-1]["message"]);self.assertFalse(any(e.get("stage")=="physics_init" for e in events))
    def test_nonempty_origin_initial_execution_missing_spawn_and_bool_coordinate(self):
        jobs=Jobs(self.root/"origin_tamper");good,_=self.run_job(jobs,None,sim=dict(self.sim,count=1))
        result_path=Path(good["result_path"]);original=json.loads(result_path.read_bytes());origin_path=result_path.parent/original["origin"]["record_path"]
        origin_bytes=origin_path.read_bytes();origin=json.loads(origin_bytes);pointer=digest(jobs.directory/"current.json")
        for change in ("bool_coordinate","missing_spawn","wrong_execution","missing_execution"):
            bad=copy.deepcopy(origin)
            if change=="bool_coordinate":bad["initial_positions"][0][0]=True
            elif change=="missing_spawn":bad.pop("spawn_status")
            elif change=="wrong_execution":bad["execution"]["body_count"]=0
            else:bad.pop("execution")
            atomic_json(origin_path,bad);sha=digest(origin_path);record=copy.deepcopy(original)
            for ref in (record["origin"],record["pose_origin"],record["pose_envelope"]["origin"]):ref["record_sha256"]=sha
            atomic_json(result_path,record);jobs.active=good["request"]
            with self.assertRaises((ValueError,KeyError)):jobs.validate(result_path,good["job_id"])
            origin_path.write_bytes(origin_bytes);atomic_json(result_path,original)
            path=jobs.prepare(self.rows,dict(self.sim,count=1),self.bake,rebake=True)
            bundle_path=path.parent/"pose_source.json";bundle=json.loads(bundle_path.read_bytes())
            raw=compat.encoded(bad);sha=compat.sha(raw);(path.parent/"provenance"/(sha+".json")).write_bytes(raw)
            bundle["origin"]["record_sha256"]=sha
            source=json.loads((path.parent/"provenance"/(bundle["source"]["record_sha256"]+".json")).read_bytes())
            for ref in (source["origin"],source["pose_origin"],source["pose_envelope"]["origin"]):ref["record_sha256"]=sha
            source_raw=compat.encoded(source);source_sha=compat.sha(source_raw);(path.parent/"provenance"/(source_sha+".json")).write_bytes(source_raw);bundle["source"]["record_sha256"]=source_sha
            atomic_json(bundle_path,bundle);jobs.active["pose_source_hash"]=digest(bundle_path);atomic_json(path,jobs.active)
            events=self.execute(path,False);self.assertFalse(any(e.get("stage")=="physics_init" for e in events))
            self.assertEqual(digest(jobs.directory/"current.json"),pointer)

if __name__=="__main__":unittest.main(verbosity=2)
