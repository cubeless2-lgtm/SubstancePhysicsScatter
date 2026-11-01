"""Execute the lane's inline loader with deliberately stale base-name modules installed."""
import hashlib
import json
import marshal
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
import uuid
import zlib
from unittest import mock
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"plugin"))

class HelperFreshness(unittest.TestCase):
    def test_stale_sys_modules_ignored_and_current_function_code_attested(self):
        lane=ROOT/"tests/designer_acceptance.py";compiled=compile(lane.read_bytes(),str(lane),"exec")
        code=next(c for c in compiled.co_consts if isinstance(c,types.CodeType) and c.co_name=="fresh_helper")
        fingerprint={"tests/"+name:hashlib.sha256((ROOT/"tests"/name).read_bytes()).hexdigest() for name in ("designer_acceptance.py","png_pixels.py","moved_fixture.py","designer_file_mask_lane.py")}
        stale={}
        for name in ("png_pixels","moved_fixture","designer_file_mask_lane"):
            module=types.ModuleType(name)
            def forbidden(*args,**kwargs):raise AssertionError("stale helper executed")
            module.signature=forbidden;module.prepare=forbidden;module.run=forbidden;stale[name]=module
        with tempfile.TemporaryDirectory(prefix="scatter_helper_fresh ") as temp:
            work=Path(temp)
            namespace=dict(ROOT=ROOT,WORK=work,evidence={},before_fingerprint=fingerprint,__file__=str(lane),Path=Path,hashlib=hashlib,types=types,sys=sys,uuid=uuid,marshal=marshal)
            namespace["fresh_helper"]=types.FunctionType(code,namespace)
            with mock.patch.dict(sys.modules,stale):
                png=namespace["fresh_helper"]("png_pixels");moved=namespace["fresh_helper"]("moved_fixture")
                mask=namespace["fresh_helper"]("designer_file_mask_lane")
                self.assertEqual(mask.image([0],1,1)[:8],b"\x89PNG\r\n\x1a\n")
                again=namespace["fresh_helper"]("png_pixels")
                self.assertNotEqual(png.__name__,again.__name__)
                self.assertIs(sys.modules["png_pixels"],stale["png_pixels"])
                self.assertIs(sys.modules["moved_fixture"],stale["moved_fixture"])
                def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
                image=work/"sample.png"
                image.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,16,0,0,0,0))+chunk(b"IDAT",zlib.compress(b"\0\x12\x34"))+chunk(b"IEND",b""))
                self.assertEqual(png.signature(image),dict(header=(1,1,16,0),decoded_sha256=hashlib.sha256(b"\x12\x34").hexdigest()))
                cache=work/"Demo_PhysicsScatter";cache.mkdir();(cache/"height.png").write_bytes(image.read_bytes())
                assets=work/"original_assets";assets.mkdir();(assets/"cube.obj").write_bytes(b"mesh")
                data={"path":str(cache/"height.png")};(cache/"current.json").write_text(json.dumps(data),encoding="utf-8")
                package=work/"Demo.sbs";root=ET.Element("package");ET.SubElement(root,"filepath",v="Demo_PhysicsScatter/height.png");ET.SubElement(root,"value",v=json.dumps(data));ET.ElementTree(root).write(package,encoding="utf-8")
                target,audit=moved.prepare(package,assets,work)
                self.assertTrue(target.is_file());self.assertTrue(audit["copy_byte_identical"])
            proof=namespace["evidence"]
            self.assertTrue(proof["helper_loader_freshness"]["inline"])
            for name,required in (("png_pixels",("decoded","signature")),("moved_fixture",("walk","owned","prepare")),("designer_file_mask_lane",("image","run"))):
                self.assertEqual(proof["helper_freshness"][name]["source_sha256"],fingerprint["tests/"+name+".py"])
                for function in required:self.assertTrue(proof["helper_freshness"][name]["functions"][function]["matches_source_compile"])

if __name__=="__main__":unittest.main(verbosity=2)
