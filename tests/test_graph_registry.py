"""Inactive pure registry: caller-owned bytes/typed projections only. No SDK."""
import copy,hashlib,json,re,struct,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter import graph_registry as registry
from substance_physics_scatter import mask_source
FIX=Path(__file__).with_name("fixtures")/"graph_registry"

def serialization_inputs():
    """Immutable actual failed run; paths and raw bytes are never rewritten."""
    from substance_physics_scatter.fileio import io_path
    case=json.loads((FIX.parent/"terminal_capture/serialization_case.json").read_text(encoding="utf-8"));base=Path(case["inspection"])
    for path,digest in case["files"].items():
        if hashlib.sha256(io_path(path).read_bytes()).hexdigest()!=digest:raise ValueError("Actual serialization fixture changed")
    producer=json.loads(io_path(base/"pre-producer.json").read_text(encoding="utf-8"));args=json.loads(io_path(Path(case["run"])/"inspector-arguments.json").read_text(encoding="utf-8"))
    packages=[dict(p,copy_xml=io_path(base/("pre-"+p["role"]+".sbs")).read_bytes()) for p in producer["packages"]]
    return dict(selection=args["selection"],packages=packages,stock_references=dict(noise=(FIX/"vertical_noise.sbs").read_bytes(),invert=(FIX/"invert.sbs").read_bytes()),forbidden_bitmap_paths=[],source_serialization_base=str(base)),producer["producer"],case

class GraphRegistry(unittest.TestCase):
    def inputs(self,name="composition"):
        cases=json.loads((FIX/"projections.json").read_text(encoding="utf-8"));case=cases[name]
        refs={role:(FIX/file).read_bytes() for role,file in (("noise","vertical_noise.sbs"),("invert","invert.sbs"))}
        packages=[dict(role="source",path=case["paths"]["source"],uid=case["source_uid"],copy_xml=(FIX/(name+".sbs")).read_bytes(),typed_view=case["typed_view"])]
        needed=("noise",) if name=="noise_only" else ("noise","invert")
        from xml.etree import ElementTree as ET
        for role in needed:
            raw=re.sub(rb'(<fileUID v=")[^"]+("/>)',lambda m:m[1]+("{"+case["stock_uids"][role]+"}").encode()+m[2],refs[role],count=1)
            graphs=[dict(identifier=g.find("identifier").get("v"),class_name="SDSBSCompGraph") for g in ET.fromstring(raw).findall("content/graph")]
            packages.append(dict(role=role,path=case["paths"][role],uid=case["stock_uids"][role],copy_xml=raw,typed_view=dict(package_uid=case["stock_uids"][role],graphs=graphs)))
        return dict(selection=case["selection"],packages=packages,stock_references=refs,forbidden_bitmap_paths=[])

    def test_two_topologies_and_whole_unselected_graph_closure(self):
        for name,topology,count in (("composition","noise_invert_terminal",3),("noise_only","noise_terminal",2),("two_graphs","noise_terminal",3)):
            data=self.inputs(name);before=copy.deepcopy(data);proof=registry.validate_source(**data)
            self.assertEqual(proof["topology"],topology);self.assertEqual(len(proof["authored_manifest"]["stocks"]),count-1)
            self.assertEqual(proof["bindings"]["terminal"]["output_id"],data["selection"]["terminal_identifier"]);self.assertEqual(proof["bindings"]["terminal"]["category"],"Output")
            self.assertEqual(proof["authored_sha256"],mask_source.signature(proof["authored_manifest"]));self.assertEqual(data,before)
            self.assertFalse(proof["feature_active"]);self.assertFalse(proof["SDK_adapter_verified"])
        data=self.inputs("two_graphs");data["packages"]=data["packages"][:2]
        with self.assertRaises(ValueError):registry.validate_source(**data)
        data=self.inputs("two_graphs")
        data["packages"][0]["copy_xml"]=data["packages"][0]["copy_xml"].replace(b'constantValueInt2 v="9 9"',b'constantValueInt2 v="10 9"',1)
        with self.assertRaises(ValueError):registry.validate_source(**data)

    def test_exact_official_UID_only_and_nonselected_stock_graph(self):
        data=self.inputs();proof=registry.validate_source(**data)
        self.assertTrue(all(s["file_uid_only"] for s in proof["authored_manifest"]["stocks"]))
        for role,needle,replacement in (("noise",b'constantValueFloat4 v="0.504999995 0.504999995 0.504999995 0.5"',b'constantValueFloat4 v="0.75 0.504999995 0.504999995 0.5"'),("invert",b'<identifier v="invert"',b'<identifier v="unknown"')):
            changed=copy.deepcopy(data);p=next(p for p in changed["packages"] if p["role"]==role)
            self.assertIn(needle,p["copy_xml"]);p["copy_xml"]=p["copy_xml"].replace(needle,replacement,1)
            with self.assertRaises(ValueError):registry.validate_source(**changed)

    def test_source_single_leaf_and_dynamic_unknown_feedback_rejected(self):
        data=self.inputs();raw=data["packages"][0]["copy_xml"]
        mutations=[(b'constantValueInt2 v="9 9"',b'constantValueInt2 v="10 9"'),(b'constantValueInt32 v="1"',b'constantValueInt32 v="3"'),(b'<name v="randomseed"/><relativeTo v="0"/><paramValue><constantValueInt32 v="0"',b'<name v="randomseed"/><relativeTo v="0"/><paramValue><constantValueInt32 v="1"'),(b'pkg:///vertical_noise?',b'pkg:///unknown?'),(b'filename v="stock/invert.sbs"',b'filename v="unowned.sbs"'),(b'<name v="outputsize"',b'<name v="pixelsize"'),(b'<identifier v="Source"',b'<identifier v="feedback"')]
        for before,after in mutations:
            self.assertIn(before,raw);changed=copy.deepcopy(data);changed["packages"][0]["copy_xml"]=raw.replace(before,after,1)
            with self.assertRaises(ValueError):registry.validate_source(**changed)
        changed=copy.deepcopy(data);changed["packages"][0]["copy_xml"]=raw.replace(b'<constantValueInt2 v="9 9"/>',b'<dynamicValue><rootnode v="1"/></dynamicValue>',1)
        with self.assertRaises(ValueError):registry.validate_source(**changed)
        changed=copy.deepcopy(data);changed["packages"][0]["copy_xml"]=raw.replace(b"<compInstance>",b"<unknownDefinition>",1).replace(b"</compInstance>",b"</unknownDefinition>",1)
        with self.assertRaises(ValueError):registry.validate_source(**changed)

    def test_typed_binding_declaration_modifier_flags_and_disorder(self):
        data=self.inputs()
        for change in (lambda g:g["nodes"][0]["reference"].update(package_uid="33333333-3333-4333-8333-333333333333"),lambda g:g["literals"][0].update(value=[True,9]),lambda g:g["literals"][0]["declaration"]["modifier"].update(value=1),lambda g:g["literals"][1]["declarations"].pop(),lambda g:g["literals"][0]["flags"].update(read_only=True),lambda g:next(p for p in g["literals"] if p["id"]=="Disorder").update(value=-0.0)):
            changed=copy.deepcopy(data);change(changed["packages"][0]["typed_view"]["graphs"][0])
            with self.assertRaises(ValueError):registry.validate_source(**changed)
        changed=copy.deepcopy(data);changed["packages"][0]["typed_view"]["graphs"][0]["literals"].append(dict(unknown=True))
        with self.assertRaises(ValueError):registry.validate_source(**changed)

    def test_budget_DTD_unknown_UID_and_package_alias(self):
        for raw in (b'<!DOCTYPE package [<!ENTITY x "x">]><package/>','<?xml version="1.0" encoding="UTF-16"?><package/>'.encode("utf-16"),b"x"*(registry.LIMITS["xml_file"]+1)):
            data=self.inputs();data["packages"][0]["copy_xml"]=raw
            with self.assertRaises(ValueError):registry.validate_source(**data)
        data=self.inputs();g=data["packages"][0]["typed_view"]["graphs"][0];old=g["nodes"][1]["id"];new=g["nodes"][0]["id"]
        data["packages"][0]["copy_xml"]=data["packages"][0]["copy_xml"].replace(('uid v="'+old+'"').encode(),('uid v="'+new+'"').encode(),1)
        with self.assertRaises(ValueError):registry.validate_source(**data)
        data=self.inputs();data["forbidden_bitmap_paths"]=[data["packages"][1]["path"]]
        with self.assertRaises(ValueError):registry.validate_source(**data)

    def test_declared_Float32_exactness_and_signed_zero(self):
        self.assertEqual(registry._float32("0.505",0.5049999952316284),struct.pack("=f",0.505).hex())
        self.assertEqual(registry._float32("-0",-0.0),struct.pack("=f",-0.0).hex())
        for token,value in (("0.505",.505),("0",-0.0),("-0",0.0),("nan",0.0),("1e999",1.0),("0",False),("0_0",0.0)):
            with self.assertRaises(ValueError):registry._float32(token,value)

    def test_no_canonical_filesystem_or_SDK_access(self):
        data=self.inputs()
        with patch("builtins.open",side_effect=AssertionError("validator I/O")),patch.object(Path,"resolve",side_effect=AssertionError("resolve")),patch.object(Path,"exists",side_effect=AssertionError("exists")),patch.object(mask_source,"logical_path",side_effect=AssertionError("live path")):
            proof=registry.validate_source(**data)
        self.assertFalse(proof["native_copy_serializer_supported"])

    def test_unused_required_stock_reference_is_prevalidated(self):
        for invalid in (object(),b"corrupt",b"",b"x"*(registry.LIMITS["xml_file"]+1)):
            data=self.inputs("noise_only");data["stock_references"]["invert"]=invalid
            with self.assertRaisesRegex(ValueError,"Official stock SHA mismatch"):registry.validate_source(**data)

    def test_serialization_actual_copy_base_and_canonical_binding_signature(self):
        from substance_physics_scatter.fileio import io_path
        data,evidence,case=serialization_inputs();before=copy.deepcopy(data);proof=registry.validate_source(**data)
        self.assertEqual(proof["topology"],"noise_invert_terminal");self.assertEqual(data,before)
        self.assertNotIn("source_xml_sha256",proof["authored_manifest"]);self.assertEqual(proof["authored_manifest"]["source_binding_scheme"],"canonical_copy_binding_v1")
        original=copy.deepcopy(data);original["packages"][0]["copy_xml"]=io_path(Path(case["run"])/"source/Source.sbs").read_bytes();original["source_serialization_base"]=str(Path(original["selection"]["package_path"]).parent)
        self.assertNotEqual(hashlib.sha256(original["packages"][0]["copy_xml"]).hexdigest(),hashlib.sha256(data["packages"][0]["copy_xml"]).hexdigest())
        self.assertEqual(mask_source.encoded(registry.validate_source(**original)),mask_source.encoded(proof))
        for name in ("composition","noise_only","two_graphs"):
            legacy=self.inputs(name)
            self.assertEqual(mask_source.encoded(registry.validate_source(**legacy)),mask_source.encoded(registry.validate_source(**legacy,source_serialization_base=None)))
            current=registry.validate_source(**legacy,source_serialization_base=str(Path(legacy["selection"]["package_path"]).parent));self.assertEqual(current["topology"],registry.validate_source(**legacy)["topology"])

    def test_serialization_wrong_base_target_namespace_and_typed_binding(self):
        data,_,_=serialization_inputs();source=data["packages"][0]["copy_xml"]
        for base in (None,str(Path(data["selection"]["package_path"]).parent),"relative",data["source_serialization_base"]+"\\."):
            bad=copy.deepcopy(data);bad["source_serialization_base"]=base
            with self.subTest(base=base),self.assertRaises(ValueError):registry.validate_source(**bad)
        from xml.etree import ElementTree as ET
        mutations=[lambda d:d["packages"][0]["typed_view"]["graphs"][0]["nodes"][0]["reference"].update(package_uid="11111111-1111-4111-8111-111111111111"),lambda d:d["packages"][1].update(path=d["packages"][2]["path"]),lambda d:d["packages"][1].update(uid=d["packages"][2]["uid"])]
        for change in mutations:
            bad=copy.deepcopy(data);change(bad)
            with self.assertRaises(ValueError):registry.validate_source(**bad)
        tree=ET.fromstring(source);deps=tree.findall("dependencies/dependency")
        for which,value in (("filename","C:/unknown.sbs"),("filename","https://unknown/stock.sbs"),("filename","../../source/stock/unknown.sbs"),("uid",deps[1].find("uid").get("v"))):
            t=ET.fromstring(source);t.findall("dependencies/dependency")[0].find(which).set("v",value);bad=copy.deepcopy(data);bad["packages"][0]["copy_xml"]=ET.tostring(t)
            with self.assertRaises(ValueError):registry.validate_source(**bad)
        t=ET.fromstring(source);paths=t.findall("content/graph/compNodes/compNode/compImplementation/compInstance/path");paths[0].set("v",paths[0].get("v")+"&unknown=1");bad=copy.deepcopy(data);bad["packages"][0]["copy_xml"]=ET.tostring(t)
        with self.assertRaises(ValueError):registry.validate_source(**bad)

    def test_serialization_validator_IO_zero_and_nonlocator_authored_not_erased(self):
        data,_,_=serialization_inputs();before=registry.validate_source(**data)
        with patch("builtins.open",side_effect=AssertionError("registry I/O")),patch.object(Path,"resolve",side_effect=AssertionError("registry resolve")),patch.object(Path,"exists",side_effect=AssertionError("registry exists")),patch.object(Path,"stat",side_effect=AssertionError("registry stat")),patch.object(mask_source,"logical_path",side_effect=AssertionError("registry live path")):
            self.assertEqual(registry.validate_source(**data),before)
        changed=copy.deepcopy(data);changed["packages"][0]["copy_xml"]=changed["packages"][0]["copy_xml"].replace(b'identifier v="Unsaved Package"',b'identifier v="New title"',1)
        self.assertNotEqual(changed["packages"][0]["copy_xml"],data["packages"][0]["copy_xml"])
        after=registry.validate_source(**changed);self.assertNotEqual(before["authored_sha256"],after["authored_sha256"])

if __name__=="__main__":unittest.main()
