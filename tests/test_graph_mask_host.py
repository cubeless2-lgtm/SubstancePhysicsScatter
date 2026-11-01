"""Pure host-value/companion tests; no Designer, native worker or UI calls."""
import copy,hashlib,json,shutil,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter import mask_source as source,graph_companion as companion
from substance_physics_scatter.fileio import io_path,logical_path

class HostMask(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_host_graph_한글 ");self.base=Path(self.temp.name);self.root=self.base/"jobs";self.root.mkdir()
        self.package=self.base/"Source.sbs";self.package.write_bytes(b"saved source bytes")
        self.selection=source.selection(dict(package_path=str(self.package),package_uid=str(uuid.uuid4()),graph_identifier="UserGraph",terminal_identifier="MyMask"))
        self.loaded=[{k:self.selection[k] for k in ("package_path","package_uid")}]
        self.ctx=dict(self.selection,graph_url="pkg:///UserGraph?dependency=19",terminal_node_id="42",output_id="MyMask",session_token=uuid.uuid4().hex,loaded_inventory_sha256=source.signature(source.inventory(self.loaded)),authored_sha256="a"*64)
        self.capture=dict(designer_version="16.0.3",selection=self.selection,context=self.ctx,pre_authored_sha256="a"*64,post_authored_sha256="a"*64,package_modified=True,disk_file_sha256=hashlib.sha256(self.package.read_bytes()).hexdigest(),captured_at="2026-10-31T00:00:00+00:00")
        self.mask=b"immutable mask fixture bytes";self.mask_hash=hashlib.sha256(self.mask).hexdigest();(self.root/"inputs").mkdir();(self.root/"inputs"/(self.mask_hash+".png")).write_bytes(self.mask)
    def tearDown(self):self.temp.cleanup()
    def request(self,op="simulate_bake",mask=True):
        job=uuid.uuid4().hex;run=self.root/"runs"/job;run.mkdir(parents=True)
        return dict(job_id=job,operation=op,output_directory=str(run),scatter_mask=dict(content_hash=self.mask_hash,path=str(self.root/"inputs"/(self.mask_hash+".png")),**companion.maskio.POLICY) if mask else None)
    def current(self,request,pointer=None,origin=None,previous=None):
        value=dict(job_id=request["job_id"],request=request)
        if pointer is not None:value[companion.KEY]=pointer
        if origin is not None:
            value["result"]=dict(job_id=request["job_id"],pose_origin=dict(job_id=origin))
            if previous is not None:value["result"]["rebake_source"]=dict(job_id=previous)
        return value
    def first(self):
        request=self.request();ref=companion.write(self.root,request,mode="current_graph_terminal",capture=self.capture)
        return self.current(request,ref,origin=request["job_id"])
    def rebake(self,previous,mode="saved_input"):
        request=self.request("bake");ref=companion.write(self.root,request,mode=mode,capture=self.capture if mode=="current_graph_terminal" else None,previous=previous)
        origin=previous.get("result",{}).get("pose_origin",{}).get("job_id",previous["job_id"])
        return self.current(request,ref,origin=origin,previous=previous["job_id"])
    def test_selection_schema_context_values_and_reselection(self):
        value=source.source(dict(schema_version=1,source_kind="graph_terminal",selection=self.selection));json.dumps(value)
        self.assertEqual(source.canonical(self.selection,[self.ctx],self.loaded),self.ctx)
        source.require_selection_context(self.ctx,copy.deepcopy(self.ctx))
        for key,value in (("graph_url","pkg:///UserGraph?dependency=20"),("terminal_node_id","43"),("session_token",uuid.uuid4().hex),("loaded_inventory_sha256","b"*64)):
            changed=dict(self.ctx,**{key:value})
            with self.subTest(key=key),self.assertRaises(ValueError):source.require_selection_context(self.ctx,changed)
        with self.assertRaises(ValueError):source.source(dict(schema_version=True,source_kind="graph_terminal",selection=self.selection))
        with self.assertRaises(ValueError):source.source(dict(schema_version=1,source_kind="graph_port",selection=self.selection))
        with self.assertRaises(ValueError):source.selection(dict(self.selection,mHandle=object()))
    def test_missing_unsaved_duplicate_and_same_UID_other_path(self):
        with self.assertRaises(ValueError):source.selection(dict(self.selection,package_path=None))
        with self.assertRaises(ValueError):source.canonical(self.selection,[self.ctx,self.ctx],self.loaded)
        with self.assertRaises(ValueError):source.canonical(self.selection,[self.ctx],self.loaded+[dict(self.loaded[0],package_path=str(self.base/"Other.sbs"))])
        with self.assertRaises(ValueError):source.canonical(self.selection,[],self.loaded)
        self.package.unlink()
        with self.assertRaises(ValueError):source.canonical(self.selection,[self.ctx],self.loaded)
    def test_capture_signature_and_no_wrapper_data(self):
        self.assertEqual(source.capture(self.capture),self.capture)
        with self.assertRaises(ValueError):source.capture(dict(self.capture,post_authored_sha256="b"*64))
        with self.assertRaises(ValueError):source.capture(dict(self.capture,package_modified=1))
        with self.assertRaises(ValueError):source.capture(dict(self.capture,SDK=object()))
        with self.assertRaises(ValueError):source.capture(dict(self.capture,context=dict(self.ctx,package_path=str(self.base/"Other.sbs"))))
    def test_normal_unsaved_edit_allowed_before_operation_but_not_during(self):
        selected=copy.deepcopy(self.ctx);edited=dict(self.ctx,authored_sha256="b"*64)
        source.require_selection_context(selected,edited)
        source.require_operation_context(edited,copy.deepcopy(edited))
        fresh=dict(self.capture,context=edited,pre_authored_sha256="b"*64,post_authored_sha256="b"*64)
        self.assertEqual(source.capture(fresh),fresh)
        with self.assertRaisesRegex(ValueError,"during operation"):source.require_operation_context(edited,dict(edited,authored_sha256="c"*64))
        with self.assertRaises(ValueError):source.require_operation_context(edited,dict(edited,graph_url="pkg:///UserGraph?dependency=20"))
        self.assertEqual(self.package.read_bytes(),b"saved source bytes")
    def test_current_saved_and_cross_mode_policy(self):
        first=self.first();record=companion.read(self.root,first)["record"]
        with self.assertRaisesRegex(ValueError,"저장된 입력"):source.input_policy(record,rebake=True,mode="current_file")
        source.input_policy(record,rebake=True,mode="saved_input")
        source.input_policy(record,rebake=False,mode="current_file")
        source.input_policy(None,rebake=True,mode="current_graph_terminal")
        with self.assertRaises(ValueError):source.input_policy(None,rebake=False,mode="saved_input")
    def test_self_origin_and_two_rebakes_flat_minimal(self):
        first=self.first();initial=companion.read(self.root,first);second=self.rebake(first);third=self.rebake(second)
        for current in (second,third):
            record=companion.read(self.root,current)
            self.assertEqual(record["record"]["pile_origin"],dict(kind="blob",job_id=first["job_id"],sha256=initial["sha256"]))
            self.assertFalse(record["record"]["capture_available"])
            self.assertLessEqual(len(record["blobs"]),2)
        self.assertEqual(len(companion.read(self.root,second)["blobs"]),1)
        self.assertEqual(companion.read(self.root,third)["record"]["previous_source"]["job_id"],second["job_id"])
        self.assertEqual((self.root/"runs"/first["job_id"]/companion.NAME).read_bytes(),initial["raw"])
    def test_native_first_and_previous_id_mismatch_rejected(self):
        first=self.first();bad=copy.deepcopy(first);bad["result"]["pose_origin"]["job_id"]=uuid.uuid4().hex
        with self.assertRaises(ValueError):companion.read(self.root,bad)
        second=self.rebake(first);second["result"]["rebake_source"]["job_id"]=uuid.uuid4().hex
        with self.assertRaises(ValueError):companion.read(self.root,second)
    def test_legacy_absent_null_saved_and_no_inferred_graph_origin(self):
        old=self.current(self.request(mask=False));self.assertIsNone(companion.read(self.root,old))
        self.assertIsNone(companion.read(self.root,old,metadata_ref=companion.MISSING))
        saved_req=self.request("bake",mask=False);ref=companion.write(self.root,saved_req,mode="saved_input",previous=old);saved=self.current(saved_req,ref)
        self.assertIsNone(ref);self.assertIsNone(companion.read(self.root,saved));self.assertIsNone(saved_req["scatter_mask"])
        self.assertFalse((self.root/"runs"/saved_req["job_id"]/companion.NAME).exists())
        old_masked=self.current(self.request());current=self.rebake(old_masked,mode="current_graph_terminal");doc=companion.read(self.root,current)["record"]
        self.assertTrue(doc["capture_available"]);self.assertFalse(doc["pile_origin_available"])
    def test_old_file_saved_stays_file_but_graph_capture_survives_two_saved(self):
        old=self.current(self.request());saved=self.rebake(old);saved_again=self.rebake(saved)
        for current in (saved,saved_again):
            self.assertNotIn(companion.KEY,current)
            self.assertIsNone(companion.read(self.root,current))
            source.input_policy(None,rebake=True,mode="current_file")
            self.assertEqual(current["request"]["scatter_mask"]["content_hash"],self.mask_hash)
        graph=self.rebake(old,mode="current_graph_terminal");first_saved=self.rebake(graph);second_saved=self.rebake(first_saved)
        for current in (graph,first_saved,second_saved):
            record=companion.read(self.root,current)["record"]
            self.assertTrue(source.graph_family(record))
            self.assertFalse(record["pile_origin_available"])
            with self.assertRaises(ValueError):source.input_policy(record,rebake=True,mode="current_file")
            source.input_policy(record,rebake=True,mode="saved_input")
        record=companion.read(self.root,second_saved)["record"]
        self.assertFalse(record["capture_available"]);self.assertTrue(record["previous_source"]["companion_available"])
        source.input_policy(record,rebake=False,mode="current_file")
        fresh_file=self.current(self.request());self.assertIsNone(companion.read(self.root,fresh_file))
    def test_explicit_missing_corrupt_and_pointer_removal_not_legacy(self):
        first=self.first();pointer=first[companion.KEY]
        with self.assertRaises(ValueError):companion.read(self.root,first,metadata_ref=companion.MISSING)
        with self.assertRaises(ValueError):companion.read(self.root,first,metadata_ref=dict(pointer,sha256="0"*64))
        removed=copy.deepcopy(first);del removed[companion.KEY]
        with self.assertRaises(ValueError):companion.read(self.root,removed)
        path=self.root/"runs"/first["job_id"]/companion.NAME;path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaises(ValueError):companion.read(self.root,first)
        path.unlink()
        with self.assertRaises(OSError):companion.read(self.root,first)
    def test_moved_root_and_historical_graph_path_is_never_opened(self):
        first=self.first();second=self.rebake(first);before=(self.root/"runs"/second["job_id"]/companion.NAME).read_bytes();moved=self.base/"moved"
        shutil.copytree(io_path(self.root),io_path(moved));self.package.unlink()
        with patch.object(source,"logical_path",side_effect=AssertionError("Historical graph path must not resolve")):
            record=companion.read(moved,second)
        self.assertEqual(record["record"]["pile_origin"]["job_id"],first["job_id"])
        self.assertEqual((moved/"runs"/second["job_id"]/companion.NAME).read_bytes(),before)
    def test_blob_missing_extra_cycle_and_identity_tamper(self):
        first=self.first();second=self.rebake(first);run=self.root/"runs"/second["job_id"];path=run/companion.NAME;doc=json.loads(path.read_bytes())
        blob=next((run/"host_provenance").iterdir());raw=blob.read_bytes();blob.unlink()
        with self.assertRaises(ValueError):companion.read(self.root,second)
        blob.write_bytes(raw);(run/"host_provenance"/("0"*64+".json")).write_bytes(b"{}")
        with self.assertRaises(ValueError):companion.read(self.root,second)
        (run/"host_provenance"/("0"*64+".json")).unlink()
        for mutate in (lambda x:x["pile_origin"].update(job_id=second["job_id"]),lambda x:x["previous_source"].update(job_id=second["job_id"]),lambda x:x.update(schema_version=3),lambda x:x.update(capture_available=True)):
            bad=copy.deepcopy(doc);mutate(bad)
            with self.assertRaises(ValueError):companion.document(bad)
    def test_already_read_previous_cannot_point_back_to_current(self):
        first=self.first();second=self.rebake(first);third=self.rebake(second)
        original_first=companion.read(self.root,first)["raw"];original_second=companion.read(self.root,second)["raw"]
        bundle=companion.read(self.root,third);doc=copy.deepcopy(bundle["record"]);previous_sha=doc["previous_source"]["sha256"];previous=json.loads(bundle["blobs"][previous_sha])
        previous["previous_source"]=dict(job_id=third["job_id"],companion_available=True,sha256="b"*64)
        raw=source.encoded(previous);digest=hashlib.sha256(raw).hexdigest();run=self.root/"runs"/third["job_id"]
        (run/"host_provenance"/(previous_sha+".json")).unlink();(run/"host_provenance"/(digest+".json")).write_bytes(raw)
        doc["previous_source"]["sha256"]=digest;raw=source.encoded(doc);(run/companion.NAME).write_bytes(raw);third[companion.KEY]["sha256"]=hashlib.sha256(raw).hexdigest()
        reads=[];actual=companion.Bundle.read
        def traced(reader,path,expected=None):reads.append(logical_path(path));return actual(reader,path,expected)
        with patch.object(companion.Bundle,"read",new=traced):
            with self.assertRaisesRegex(ValueError,"already-read|Already-read|cycle"):companion.read(self.root,third)
        self.assertEqual(len(reads),3);self.assertTrue(all(p.is_relative_to(logical_path(run)) for p in reads))
        self.assertEqual(companion.read(self.root,first)["raw"],original_first);self.assertEqual(companion.read(self.root,second)["raw"],original_second)
    def test_known_job_cycle_and_conflicting_role_SHA_without_history_reads(self):
        first=self.first();second=self.rebake(first);a=copy.deepcopy(companion.read(self.root,second)["record"]);b=copy.deepcopy(a)
        a_id=a["job_id"];b_id=uuid.uuid4().hex;sha_a="a"*64;sha_b="b"*64
        a["pile_origin_available"]=False;a["pile_origin"]=None;a["previous_source"]=dict(job_id=b_id,companion_available=True,sha256=sha_b)
        b.update(job_id=b_id,pile_origin_available=False,pile_origin=None,previous_source=dict(job_id=a_id,companion_available=True,sha256=sha_a))
        with self.assertRaisesRegex(ValueError,"cycle"):companion.known_links(a,sha_a,{"previous":b},[("previous",b_id,sha_b)])
        with self.assertRaisesRegex(ValueError,"Conflicting raw SHA"):companion.known_links(a,sha_a,{"origin":b,"previous":b},[("origin",b_id,sha_b),("previous",b_id,"c"*64)])
    def test_write_failure_before_and_after_publish_preserves_source(self):
        first=self.first();original=companion.read(self.root,first)["raw"]
        for publish in (False,True):
            request=self.request("bake")
            def fail(path,raw):
                if publish:companion._atomic(path,raw)
                raise OSError("injected host write failure")
            with self.assertRaises(OSError):companion.write(self.root,request,mode="saved_input",previous=first,writer=fail)
            run=self.root/"runs"/request["job_id"]
            self.assertFalse((run/companion.NAME).exists());self.assertFalse((run/"host_provenance").exists())
            self.assertEqual(companion.read(self.root,first)["raw"],original)
    def test_file_total_budget_and_duplicate_JSON_rejected(self):
        first=self.first();path=self.root/"runs"/first["job_id"]/companion.NAME;raw=path.read_bytes()
        path.write_bytes(b" "*(companion.MAX_FILE+1))
        with self.assertRaises(ValueError):companion.read(self.root,first)
        path.write_bytes(raw)
        with patch.object(companion,"MAX_TOTAL",len(raw)-1):
            with self.assertRaises(ValueError):companion.read(self.root,first)
        with self.assertRaises(ValueError):companion.decode(b'{"schema_version":2,"schema_version":1}')
    def test_schema1_assumed_capture_model_read_only_not_rewritten(self):
        request=self.request();job=request["job_id"];legacy=dict(schema_version=1,job_id=job,operation=request["operation"],mode="current_graph",snapshot_sha256=self.mask_hash,capture_available=True,pile_origin_available=True,pile_origin=dict(kind="self",job_id=job),previous_source=None,capture=dict(pre_signature_sha256="a"*64,post_signature_sha256="a"*64,designer_version="16.0.3",package_path=str(logical_path(self.package)),package_uid=self.selection["package_uid"],graph_url="pkg:///source?dependency=1",instance_path=[],source_node_id="1",output_id="mask",captured_at="2026-10-31T00:00:00+00:00"))
        raw=source.encoded(legacy);path=self.root/"runs"/job/companion.NAME;path.write_bytes(raw);pointer=dict(path=companion.NAME,sha256=hashlib.sha256(raw).hexdigest(),schema_version=1);current=self.current(request,pointer,origin=job)
        self.assertEqual(companion.read(self.root,current)["raw"],raw);second=self.rebake(current)
        self.assertEqual(companion.read(self.root,second)["blobs"][pointer["sha256"]],raw)
        self.assertEqual(path.read_bytes(),raw)
    def test_host_source_schema_does_not_extend_native_request(self):
        schema=json.loads((ROOT/"schemas/mask_source.schema.json").read_bytes());self.assertFalse(schema["additionalProperties"])
        native=json.loads((ROOT/"schemas/request.schema.json").read_bytes());self.assertNotIn("mask_source",native["properties"]);self.assertNotIn(companion.KEY,native["properties"])

if __name__=="__main__":unittest.main()
