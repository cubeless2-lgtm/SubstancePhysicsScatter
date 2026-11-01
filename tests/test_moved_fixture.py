from pathlib import Path
import ast
import json
import tempfile
import unittest
from xml.etree import ElementTree as ET
from unittest import mock
import moved_fixture
from moved_fixture import prepare,fingerprint,owned

class MovedFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="scatter_move_원본 ");self.work=Path(self.temp.name)
        self.package=self.work/"Demo.sbs";self.cache=self.work/"Demo_PhysicsScatter";self.cache.mkdir()
        self.assets=self.work/"original_assets";self.assets.mkdir();(self.assets/"cube & box.obj").write_bytes(b"mesh")
        (self.cache/"height.png").write_bytes(b"pixels")
        data={"nested":{"path":str(self.cache/"height.png"),"source":str(self.assets/"cube & box.obj")},"name":"cube & box.obj"}
        (self.cache/"current.json").write_text(json.dumps(data),encoding="utf-8")
        (self.cache/"result.json").write_text(json.dumps(data),encoding="utf-8")
        tree=ET.Element("package");resource=ET.SubElement(tree,"resource");ET.SubElement(resource,"filepath",v="Demo_PhysicsScatter/height.png")
        ET.SubElement(tree,"value",v=json.dumps(data,ensure_ascii=False));ET.ElementTree(tree).write(self.package,encoding="utf-8",xml_declaration=True)
    def tearDown(self):self.temp.cleanup()
    def test_relative_xml_escaped_json_rebase_byte_identity_and_park(self):
        main_before={str(p):p.read_bytes() for p in (self.package,self.cache/"current.json",self.assets/"cube & box.obj")}
        package,audit=prepare(self.package,self.assets,self.work)
        self.assertTrue(audit["relative_linked_unchanged"]);self.assertTrue(audit["copy_byte_identical"])
        self.assertEqual(audit["oldmain_fallback_count"],0);self.assertEqual(audit["destination_injected_count"],0)
        self.assertGreater(audit["source_prefix_count"],0);self.assertTrue(audit["source_prefix_absent_after_park"])
        self.assertTrue(audit["destination_relative_linked_files_exist"])
        self.assertEqual(audit["main_proof_sha256_before"],audit["main_proof_sha256_after"])
        tree=ET.parse(package);self.assertEqual(tree.find("resource/filepath").get("v"),"Demo_PhysicsScatter/height.png")
        decoded=json.loads(tree.find("value").get("v"));self.assertIn("migration",decoded["nested"]["path"])
        self.assertIn("source",Path(decoded["nested"]["path"]).parts);self.assertNotIn("moved",Path(decoded["nested"]["path"]).parts)
        self.assertEqual(decoded["name"],"cube & box.obj")
        self.assertEqual(fingerprint(Path(audit["parked_source"])),fingerprint(package.parent))
        self.assertEqual(main_before,{str(p):p.read_bytes() for p in map(Path,main_before)})
        self.assertEqual((package.parent/"Demo_PhysicsScatter/result.json").read_bytes(),(self.cache/"result.json").read_bytes())
        self.assertEqual(audit["immutable_json_rewritten_count"],0)
        with self.assertRaisesRegex(ValueError,"already exists"):prepare(self.package,self.assets,self.work)
    def test_owned_paths_cannot_escape_unique_work(self):
        for path in (self.work,self.work/".."/"elsewhere"):
            with self.assertRaisesRegex(ValueError,"escapes"):owned(path,self.work)
    def test_absolute_linked_paths_are_rejected_without_parking_main(self):
        tree=ET.parse(self.package);tree.find("resource/filepath").set("v",str(self.cache/"height.png"));tree.write(self.package,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"relative Linked"):prepare(self.package,self.assets,self.work)
        self.assertTrue(self.cache.exists());self.assertTrue(self.assets.exists());self.assertTrue(self.package.exists())
    def test_missing_owned_path_is_rejected(self):
        (self.cache/"current.json").write_text(json.dumps({"path":str(self.cache/"missing.png")}),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"missing"):prepare(self.package,self.assets,self.work)
        self.assertTrue(self.cache.exists())
    def test_unconverted_oldmain_path_is_detected_in_xml(self):
        tree=ET.parse(self.package);ET.SubElement(tree.getroot(),"unknown_path",v=str(self.cache/"height.png"));tree.write(self.package,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"oldmain fallback"):prepare(self.package,self.assets,self.work)
        self.assertTrue(self.cache.exists())
    def test_destination_injection_is_detected_before_copy(self):
        original=moved_fixture.inspect
        def inject(directory,package_name,old_roots,destination):
            file=directory/"Demo_PhysicsScatter/current.json"
            value=json.loads(file.read_text(encoding="utf-8"));value["bad_destination"]=str(destination/"Demo_PhysicsScatter/height.png")
            file.write_text(json.dumps(value),encoding="utf-8")
            return original(directory,package_name,old_roots,destination)
        with mock.patch.object(moved_fixture,"inspect",side_effect=inject):
            with self.assertRaisesRegex(ValueError,"destination path injected"):prepare(self.package,self.assets,self.work)
        self.assertFalse((self.work/"migration/moved").exists());self.assertTrue(self.cache.exists())
    def test_actual_stage2_then_pose_compat_calls_have_distinct_owners(self):
        script=Path(__file__).with_name("designer_acceptance.py");tree=ast.parse(script.read_text(encoding="utf-8"))
        calls=sorted((node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="prepare_moved_fixture"),key=lambda node:node.lineno)
        self.assertEqual(len(calls),2)
        names=[next((ast.literal_eval(k.value) for k in call.keywords if k.arg=="namespace"),"migration") for call in calls]
        self.assertEqual(names,["migration","legacy_migration"])
        # Execute the actual two call configurations in their real order when STAGE2 and POSE_COMPAT are true.
        prepared=[prepare(self.package,self.assets,self.work,namespace=name) for name in names]
        self.assertNotEqual(prepared[0][0],prepared[1][0])
        self.assertTrue(all(package.is_file() and evidence["main_proof_untouched"] for package,evidence in prepared))

if __name__=="__main__":unittest.main(verbosity=2)
