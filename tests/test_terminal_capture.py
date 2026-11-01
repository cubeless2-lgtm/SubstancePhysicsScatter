"""Inactive adapter boundaries. Pure replay/failure injection does not prove SDK ABI."""
import ast,copy,hashlib,json,os,struct,sys,tempfile,types,unittest,uuid,zlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter import terminal_capture as cap,mask_source,graph_registry
import test_graph_registry as registry_fixtures
FIX=Path(__file__).with_name("fixtures")/"terminal_capture"/"observed_literals.json"

def png(path):
    row=b"".join(struct.pack(">H",i*127) for i in range(512));raw=(b"\0"+row)*512
    def chunk(t,b):return struct.pack(">I",len(b))+t+b+struct.pack(">I",zlib.crc32(t+b)&0xffffffff)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",512,512,16,0,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b""))
    return hashlib.sha256(row*512).hexdigest()

class FakeAPIError(BaseException):pass

class Replay:
    """Only adapter protocol callbacks; no imitation of the SDK graph engine."""
    errors=(Exception,FakeAPIError)
    def __init__(self,root,name="noise_only"):
        self.data=registry_fixtures.GraphRegistry().inputs(name);self.root=root;self.calls=dict(copy=0,compute=0,save=0,collect=0);self.fault=None;self.hook=None
        mapping={p["path"]:str(root/("Source.sbs" if p["role"]=="source" else "stock/"+("vertical_noise.sbs" if p["role"]=="noise" else "invert.sbs"))) for p in self.data["packages"]}
        def rebase(v):
            if type(v) is str:return mapping.get(v,v)
            if type(v) is list:return [rebase(x) for x in v]
            if type(v) is dict:return {k:rebase(x) for k,x in v.items()}
            return v
        self.data=rebase(self.data);self.selected=self.data["selection"];self.urls={g["identifier"]:"pkg:///"+g["identifier"]+"?dependency=1" for g in self.data["packages"][0]["typed_view"]["graphs"]}
        self.inventory=mask_source.inventory([dict(package_path=p["path"],package_uid=p["uid"]) for p in self.data["packages"]]);self.modified=False
        self.context_extra={};self.templates=json.loads(FIX.read_text(encoding="utf-8"))["templates"]
        for p in self.data["packages"]:Path(p["path"]).parent.mkdir(parents=True,exist_ok=True);Path(p["path"]).write_bytes(p["copy_xml"])
    def assert_thread(self):pass
    def lifetime(self,selected):
        graph=next(g for g in self.data["packages"][0]["typed_view"]["graphs"] if g["identifier"]==selected["graph_identifier"])
        return dict(selected,graph_url=self.urls[selected["graph_identifier"]],terminal_node_id=graph["terminal"]["node_id"],output_id=graph["terminal"]["output_id"],session_token=cap._SESSION_TOKEN,loaded_inventory_sha256=mask_source.signature(self.inventory),**self.context_extra)
    def state(self,identities,read):
        rows=[]
        for i in identities:
            raw=read(i["path"]);rows.append(dict(role=i["role"],identity={k:i[k] for k in ("path","uid")},modified=self.modified if i["role"]=="source" else False,disk_sha256=hashlib.sha256(raw).hexdigest(),disk_bytes=len(raw)))
        return dict(packages=rows,inventory=copy.deepcopy(self.inventory))
    def inspect(self,selected,read):
        identities=[{k:p[k] for k in ("role","path","uid")} for p in self.data["packages"]]
        if selected!=self.selected:raise ValueError(mask_source.RESELECT)
        return dict(selection=selected,identities=identities,protection=self.state(identities,read),lifetime=self.lifetime(selected),source_graph_urls=copy.deepcopy(self.urls),original_locator_tokens={p["role"]:[graph_registry._leaf(d,"filename") for d in graph_registry._parse(p["copy_xml"]).findall("dependencies/dependency")] for p in self.data["packages"]},reference_bindings=[],public_caps=dict(replayed=True),designer_version="pure-test; not SDK")
    def copy(self,identity,target):
        self.calls["copy"]+=1
        if self.fault=="copy":raise FakeAPIError("injected native-copy BaseException")
        raw=next(p["copy_xml"] for p in self.data["packages"] if p["role"]==identity["role"])
        if identity["role"]=="source":
            for row in self.data["packages"]:
                if row["role"]=="source":continue
                token=b"stock/"+(b"vertical_noise.sbs" if row["role"]=="noise" else b"invert.sbs")
                raw=raw.replace(token,os.path.relpath(row["path"],target.parent).replace("\\","/").encode("utf-8"))
        if self.fault=="locator" and identity["role"]=="source":raw=raw.replace(b'vertical_noise.sbs',b'unknown.sbs')
        target.write_bytes(raw)
    def references(self,read):return self.data["stock_references"]
    def collect(self,snapshot,packages,partial):
        self.calls["collect"]+=1;result=copy.deepcopy(packages);evidence=dict(schema_version=1,literals=[],xml_bindings=[])
        for p in result:
            p["typed_view"]=copy.deepcopy(next(x["typed_view"] for x in self.data["packages"] if x["role"]==p["role"]))
            if p["role"]!="source":continue
            for g in p["typed_view"]["graphs"]:
                by_id={n["id"]:n for n in g["nodes"]};projected=[]
                for literal in g["literals"]:
                    node=None if literal["owner"]=="graph" else by_id[literal["owner"]];role="graph" if node is None else "noise" if node["reference"]["identifier"]=="vertical_noise" else "invert"
                    observed=copy.deepcopy(self.templates[role+"/"+literal["id"]]);observed.update(owner=dict(package_path=p["path"],package_uid=p["uid"],graph_identifier=g["identifier"],graph_url=self.urls[g["identifier"]],node_id=None if node is None else node["id"],definition="SDSBSCompGraph" if node is None else node["definition"]),role=role,property_id=literal["id"],function=None,connections=[],binding_basis="strict_copy_XML_no_dynamic" if node is None else "public_node_unbound")
                    # Current value is the pure memory fixture; defaults/declarations remain actual captured templates.
                    observed["current"]=dict(class_name=literal["wrapper"],type=literal["value_type"],value=literal["value"])
                    if "value_id" in literal:observed["current"]["value_id"]=literal["value_id"]
                    projection,row=cap._project_literal(observed);projected.append(projection);evidence["literals"].append(row)
                g["literals"]=projected
                evidence["xml_bindings"].append(dict(package_path=p["path"],package_uid=p["uid"],graph_identifier=g["identifier"],graph_url=self.urls[g["identifier"]],xml_graph_uid=g["uid"],node_outputs=[dict(node_id=n["id"],SDK_output_property_id=n["output"]["id"],xml_output_uid=n["output"]["uid"]) for n in g["nodes"]],basis="numeric UIDs from copy XML only, linked by canonical package/graph identifier/URL and node/property IDs"))
        if self.hook:self.hook(self,result,evidence)
        return result,evidence
    def compute(self,selected):self.calls["compute"]+=1
    def save(self,selected,path):self.calls["save"]+=1;png(path)
    def run(self,inspection,selected_context=None):
        return cap._operate(selection=self.selected,selected_context=selected_context,operation_id=uuid.uuid4().hex,owned_directory=self.root,forbidden_bitmap_paths=[],runtime=self,inspection=inspection)

class TerminalCapture(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def replay(self,name="noise_only"):return Replay(self.root,name)
    def test_actual_templates_projection_registry_default_signature_handoff(self):
        r=self.replay("two_graphs");before={p["path"]:Path(p["path"]).read_bytes() for p in r.data["packages"]}
        selection=r.run(True);self.assertEqual(selection["counts"],dict(copies=3,copy_limit=3,compute=0,PNG=0,worker=0));self.assertFalse(selection["feature_active"])
        captured=r.run(False,selection["selected_context"]);self.assertEqual(captured["counts"],dict(copies=6,copy_limit=6,compute=1,PNG=1,worker=0));self.assertEqual(r.calls["copy"],9)
        payload=captured["operation_authored_payload"];self.assertEqual(mask_source.signature(payload),captured["capture"]["context"]["authored_sha256"])
        self.assertEqual(cap._json(json.loads(cap._json(captured))),cap._json(captured));self.assertEqual(captured["png"]["decoded_u16be_sha256"],png(self.root/"independent.png"))
        self.assertEqual(before,{p:Path(p).read_bytes() for p in before});self.assertEqual(set(sys.modules).intersection({"sd","PySide6"}),set())
    def test_noise_two_package_counts_and_real_hash_no_placeholder(self):
        r=self.replay();selected=r.run(True);self.assertEqual(selected["counts"]["copies"],2)
        result=r.run(False,selected["selected_context"]);self.assertEqual(result["counts"]["copies"],4)
        self.assertNotEqual(selected["selected_context"]["authored_sha256"],"0"*64);self.assertEqual(result["capture"]["context"],selected["selected_context"])
    def test_authored_edit_between_operations_allowed_inside_operation_rejected(self):
        r=self.replay("two_graphs");selected=r.run(True);source=r.data["packages"][0]
        old=b'<constantValueBool v="0"/>';self.assertIn(old,source["copy_xml"]);source["copy_xml"]=source["copy_xml"].replace(old,b'<constantValueBool v="1"/>',1)
        for g in source["typed_view"]["graphs"]:
            for literal in g["literals"]:
                if literal["id"]=="invert":literal["value"]=True
        r.modified=True;capture=r.run(False,selected["selected_context"])
        self.assertNotEqual(capture["capture"]["context"]["authored_sha256"],selected["selected_context"]["authored_sha256"])
        def changed(runtime,packages,evidence):
            if runtime.calls["collect"]%2==0:evidence["literals"][0]["default"]["value"]=[7,8]
        r.hook=changed
        with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected["selected_context"])
        self.assertEqual(caught.exception.record["counts"]["compute"],1);self.assertEqual(caught.exception.record["counts"]["worker"],0)
        self.assertFalse((Path(caught.exception.record["work_directory"])/"handoff.json").exists())
    def test_stale_host_same_token_URL_identity_inventory_rejected_before_copy(self):
        r=self.replay();selected=r.run(True)
        for key,value in (("graph_url","pkg:///reloaded?dependency=99"),("package_uid",str(uuid.uuid4())),("loaded_inventory_sha256","a"*64),("session_token",uuid.uuid4().hex),("output_id","other")):
            stale=copy.deepcopy(selected["selected_context"]);stale[key]=value;before=r.calls.copy()
            with self.subTest(key=key),self.assertRaises(cap.CaptureError) as caught:r.run(False,stale)
            self.assertEqual(caught.exception.record["counts"]["copies"],0);self.assertEqual(r.calls,before)
    def test_producer_failures_compute_zero_raw_and_plain_evidence_preserved(self):
        r=self.replay();selected=r.run(True)
        mutations=[lambda p,e:e["literals"][0]["default"].update(value=[7,8]),lambda p,e:e["literals"][0]["default"].update(class_name="SDValueFloat"),lambda p,e:e["literals"][0]["owner"].update(graph_url="pkg:///wrong"),lambda p,e:e["literals"][0].update(binding_basis="unknown"),lambda p,e:e["literals"][0]["current"]["type"].update(id="wrong"),lambda p,e:e["xml_bindings"][0].update(xml_graph_uid="999")]
        for mutation in mutations:
            r.hook=lambda runtime,p,e:mutation(p,e)
            with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected["selected_context"])
            record=caught.exception.record;self.assertEqual(record["counts"]["compute"],0);self.assertEqual(record["counts"]["worker"],0)
            work=Path(record["work_directory"]);self.assertTrue((work/"pre-source.sbs").is_file());self.assertTrue((work/"pre-producer.json").is_file());self.assertFalse((work/"handoff.json").exists())
    def test_strict_unknown_source_stock_locator_sparse_and_copy_BaseException(self):
        r=self.replay();selected=r.run(True)
        for fault in ("copy","locator"):
            r.fault=fault
            with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected["selected_context"])
            self.assertEqual(caught.exception.record["counts"]["compute"],0);self.assertTrue(caught.exception.record["original_protection_equal"])
        r.fault=None;source=r.data["packages"][0];original=source["copy_xml"]
        for raw in (original.replace(b'constantValueInt2 v="9 9"',b'constantValueInt2 v="10 9"',1),original.replace(b'constantValueInt32 v="1"',b'constantValueInt32 v="3"',1),original.replace(b'<constantValueInt2 v="9 9" />',b'<dynamicValue/>',1)):
            self.assertNotEqual(raw,original)
            source["copy_xml"]=raw
            with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected["selected_context"])
            self.assertEqual(caught.exception.record["counts"]["compute"],0)
        source["copy_xml"]=original;noise=r.data["packages"][1];noise["copy_xml"]+=b" "
        with self.assertRaises(cap.CaptureError) as caught:r.run(False,selected["selected_context"])
        self.assertEqual(caught.exception.record["counts"]["compute"],0)
        sparse_root=self.root/"sparse";sparse_root.mkdir();sparse=Replay(sparse_root,"composition")
        for graph in sparse.data['packages'][0]['typed_view']['graphs']:
            for literal in graph['literals']:
                if literal['id']=='invert':literal['value']=False
        with self.assertRaisesRegex(cap.CaptureError,"sparse Bool"):sparse.run(True)

    def test_actual_native_sparse_true_producer_and_registry_reject_false_duplicate_dynamic(self):
        from xml.etree import ElementTree as ET
        base=ROOT/'output/GraphMaskReview/88eed9b1aa994942882ee8ce7393919e/Scatter_PhysicsScatter/scatter_edf936a1bb4a4b99a40cb22a541cbbde/terminal_operations/b804f77b813945a4ab185965b7f7ce73'
        observed=json.loads((base/'pre-producer.json').read_text(encoding='utf8'))
        packages=[dict(row,copy_xml=(base/('pre-'+row['role']+'.sbs')).read_bytes()) for row in observed['packages']]
        evidence=observed['producer'];urls={r['graph_identifier']:r['graph_url'] for r in evidence['xml_bindings']}
        selection=json.loads((base/'preflight.json').read_text(encoding='utf8'))['selection']
        refs={role:(registry_fixtures.FIX/name).read_bytes() for role,name in (('noise','vertical_noise.sbs'),('invert','invert.sbs'))}
        def verify(p,e):
            cap._validate_producer(p,e,urls)
            return graph_registry.validate_source(selection=selection,packages=p,stock_references=refs,forbidden_bitmap_paths=[],source_serialization_base=str(base))
        before=[row['copy_xml'] for row in packages];proof=verify(packages,evidence)
        self.assertTrue(proof['authored_sha256']);self.assertEqual(before,[row['copy_xml'] for row in packages])
        for fault in ('false','duplicate','dynamic','default_wrapper'):
            p=copy.deepcopy(packages);e=copy.deepcopy(evidence)
            literal=next(v for g in p[0]['typed_view']['graphs'] for v in g['literals'] if v['id']=='invert')
            row=next(v for v in e['literals'] if v['property_id']=='invert')
            if fault=='false':literal['value']=False;row['current']['value']=False
            elif fault=='dynamic':literal['function']={'unapproved':'binding'}
            elif fault=='default_wrapper':row['default']['class_name']='SDValueInt'
            else:
                tree=ET.fromstring(p[0]['copy_xml']);owner=next(n for n in tree.findall('content/graph/compNodes/compNode') if n.find('uid').get('v')==literal['owner'])
                params=owner.find('compImplementation/compInstance/parameters')
                for _ in range(2):params.append(ET.fromstring('<parameter><name v="invert"/><relativeTo v="0"/><paramValue><constantValueBool v="1"/></paramValue></parameter>'))
                p[0]['copy_xml']=ET.tostring(tree)
            with self.subTest(fault=fault),self.assertRaises(ValueError):verify(p,e)
    def test_inspector_second_observation_change_never_adopts_context(self):
        r=self.replay()
        def change(runtime,p,e):
            if runtime.calls["collect"]==2:runtime.urls[runtime.selected["graph_identifier"]]="pkg:///new?dependency=5"
        r.hook=change
        with self.assertRaises(cap.CaptureError) as caught:r.run(True)
        self.assertEqual(caught.exception.record["counts"]["compute"],0);self.assertNotIn("selected_context",caught.exception.record)
    def test_owned_no_overwrite_budget_opaque_and_bounded_png(self):
        operation=uuid.uuid4().hex;owned=cap._Owned(self.root,operation)
        with self.assertRaises(FileExistsError):cap._Owned(self.root,operation)
        with self.assertRaises(ValueError):owned.evidence("opaque",dict(value=object()))
        with self.assertRaises(ValueError):owned.evidence("tuple",dict(value=(1,2)))
        bad=self.root/"large.sbs";bad.write_bytes(b"x"*(cap._MAX_FILE+1))
        with self.assertRaises(ValueError):owned.read(bad)
        target=owned.path("terminal.png");digest=png(target);self.assertEqual(cap._png(target)["decoded_u16be_sha256"],digest)
        target.write_bytes(target.read_bytes()[:-3])
        with self.assertRaises(ValueError):cap._png(target)
    def test_failure_before_save_or_after_compute_has_no_handoff_or_source_mutation(self):
        r=self.replay();selection=r.run(True);before={p["path"]:Path(p["path"]).read_bytes() for p in r.data["packages"]}
        def fail(selected):raise FakeAPIError("injected compute failure")
        r.compute=fail
        with self.assertRaises(cap.CaptureError) as caught:r.run(False,selection["selected_context"])
        self.assertEqual(caught.exception.record["counts"]["compute"],1);self.assertEqual(r.calls["save"],0)
        self.assertTrue(caught.exception.record["original_protection_equal"]);self.assertEqual(before,{p:Path(p).read_bytes() for p in before})
        self.assertNotIn("selected_context",caught.exception.record)
    def test_sdk_literal_formatter_never_gets_image_or_opaque(self):
        for name in ("SDValueTexture","SDTexture","Unknown"):
            typ=type(name,(),dict(getClassName=lambda s:name,get=lambda s:(_ for _ in ()).throw(AssertionError("forbidden image getter"))))
            with self.assertRaisesRegex(ValueError,"Unregistered literal wrapper"):cap._SDK()._value(typ())
    def test_terminal_current_type_save_hook_and_single_get(self):
        # Extract only actual production method; imports bind minimal SDK names, not a fake graph engine.
        source=ast.parse(Path(cap.__file__).read_text(encoding="utf-8"));method=next(n for c in source.body if isinstance(c,ast.ClassDef) and c.name=="_SDK" for n in c.body if isinstance(n,ast.FunctionDef) and n.name=="save")
        method=copy.deepcopy(method);method.body=[n for n in method.body if not isinstance(n,ast.ImportFrom)]
        class Texture:
            def getSize(s):return types.SimpleNamespace(x=512,y=512)
            def getBytesPerPixel(s):return 2
            def getPixelFormat(s):return 16
        class Value:
            gets=0
            def getClassName(s):return "SDValueTexture"
            def getType(s):return dict(class_name="SDTypeCustom",id="SDTexture",modifier=dict(name="Auto",value=0))
            def get(s):s.gets+=1;return texture
        class Node:
            def getPropertyValue(s,p):return value
        texture=Texture();value=Value();events=[];namespace=dict(SDValueTexture=Value,SDTexture=Texture,SBSPixelFormat=types.SimpleNamespace(LUM16=16),_save_texture=lambda t,p:events.append((t,p)))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(cap.__file__),"exec"),namespace)
        runtime=types.SimpleNamespace(_manager=lambda:None,_selected=lambda a,b:(None,None,Node(),None),_type=lambda t:t)
        namespace["save"](runtime,{},self.root/"not-saved.png");self.assertEqual(value.gets,1);self.assertEqual(events,[(texture,self.root/"not-saved.png")])
        value.getType=lambda:dict(class_name="SDTypeTexture",id="SDTypeTexture",modifier=dict(name="Auto",value=0))
        with self.assertRaisesRegex(ValueError,"SDTypeCustom"):namespace["save"](runtime,{},self.root/"bad.png")
        self.assertEqual(value.gets,1)

    def test_actual_serialization_producer_signature_and_owned_base_binding(self):
        data,evidence,case=registry_fixtures.serialization_inputs();proof=graph_registry.validate_source(**data)
        graph_urls={row["graph_identifier"]:row["graph_url"] for row in evidence["xml_bindings"]}
        cap._validate_producer(data["packages"],evidence,graph_urls);combined,digest=cap._signature(proof,evidence)
        self.assertEqual(mask_source.signature(json.loads(cap._json(combined))),digest)
        original_source=copy.deepcopy(data);original_source["packages"][0]["copy_xml"]=Path(case["run"]).joinpath("source/Source.sbs").read_bytes();original_source["source_serialization_base"]=str(Path(data["selection"]["package_path"]).parent)
        combined_again,digest_again=cap._signature(graph_registry.validate_source(**original_source),evidence);self.assertEqual((combined_again,digest_again),(combined,digest))
        lifetime=json.loads(Path(case["inspection"]).joinpath("preflight.json").read_text(encoding="utf-8"))["lifetime"]
        before_context=cap._context(lifetime,digest);after_context=cap._context(lifetime,digest_again)
        mask_source.require_operation_context(before_context,after_context)
        self.assertEqual(json.loads(cap._json(dict(context=after_context,combined=combined)))["context"],before_context)
        owned=cap._Owned(self.root,uuid.uuid4().hex);target=owned.path("pre-source.sbs");target.write_bytes(data["packages"][0]["copy_xml"])
        row=dict(copy_path=str(target),serialization_base=str(target.parent));self.assertEqual(cap._serialization_base(owned,row),str(owned.work))
        for bad in (dict(row,serialization_base=str(self.root)),dict(row,copy_path=data["selection"]["package_path"])):
            with self.assertRaisesRegex(ValueError,"Owned source copy/base mismatch"):cap._serialization_base(owned,bad)

    def test_production_copy_stage_passes_actual_owned_parent(self):
        r=self.replay();actual=graph_registry.validate_source;seen=[]
        def checked(**kwargs):
            base=kwargs["source_serialization_base"];self.assertEqual(Path(base).parent,self.root);self.assertTrue((Path(base)/"pre-source.sbs").is_file());seen.append(base);return actual(**kwargs)
        with patch.object(cap.graph_registry,"validate_source",side_effect=checked):result=r.run(True)
        self.assertEqual(len(seen),1);self.assertEqual(result["counts"]["compute"],0)

if __name__=="__main__":unittest.main()
