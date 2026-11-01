"""Schema checks complement semantic host/native and decoded-pixel validation."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from jsonschema import Draft202012Validator,RefResolver,ValidationError
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"plugin"))
from substance_physics_scatter.core import Jobs
from test_mask_decoder import png

class MaskSchema(unittest.TestCase):
    def test_current_request_result_empty_nonempty_and_format1_boundary(self):
        schemas={p.name:json.loads(p.read_text(encoding="utf-8")) for p in (ROOT/"schemas").glob("*.json")}
        for value in schemas.values():Draft202012Validator.check_schema(value)
        with tempfile.TemporaryDirectory(prefix="scatter_schema_") as temp:
            root=Path(temp);mask=root/"black.png";mask.write_bytes(png(b"\0\0"))
            validators={name:Draft202012Validator(schemas[name],resolver=RefResolver(base_uri=(ROOT/"schemas").as_uri()+"/",referrer=schemas[name],store={((ROOT/"schemas"/key).as_uri()):value for key,value in schemas.items()})) for name in ("request.schema.json","result.schema.json")}
            for name,value in (("none",None),("empty",mask)):
                jobs=Jobs(root/name);path=jobs.prepare(ROOT/"tests/fixtures/cube.obj",dict(count=1,seconds=.1),dict(resolution=16),scatter_mask=value)
                validators["request.schema.json"].validate(jobs.active)
                p=subprocess.run([str(ROOT/"build/Release/scatter_worker.exe"),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=30)
                self.assertEqual(p.returncode,0,p.stdout+p.stderr)
                result=json.loads((path.parent/"result.json").read_text(encoding="utf-8"));validators["result.schema.json"].validate(result)
                if name=="empty":
                    result["physics_input_format_version"]=1
                    with self.assertRaises(ValidationError):validators["result.schema.json"].validate(result)
                    result["physics_input_format_version"]=2;result["attempt_count"]=True
                    with self.assertRaises(ValidationError):validators["result.schema.json"].validate(result)

if __name__=="__main__":unittest.main(verbosity=2)
