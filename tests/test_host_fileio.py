"""Emulate embedded Python rejecting ordinary MAX_PATH I/O, while extended I/O succeeds."""
import contextlib
import hashlib
import json
import os
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
from substance_physics_scatter.core import Jobs,atomic_json,digest
from substance_physics_scatter.fileio import io_path,logical_path

class HostFileIO(unittest.TestCase):
    @unittest.skipUnless(os.name=="nt","Windows extended Unicode path contract")
    def test_embedded_max_path_guard_sim_rebake_promotion_and_ownership(self):
        with tempfile.TemporaryDirectory(prefix="scatter_embedded_한글 ") as temporary:
            base=Path(temporary);directory=base
            while len(str(directory))<280:directory=directory/("긴경로_cache_"+"x"*20)
            observed=[]
            def checked(path,operation):
                value=os.fspath(path)
                if len(value)>260:
                    if not value.startswith("\\\\?\\"):raise FileNotFoundError("Emulated embedded MAX_PATH rejection: "+operation)
                    observed.append(operation)
            with contextlib.ExitStack() as stack:
                for name in ("open","stat","mkdir","unlink"):
                    original=getattr(Path,name)
                    def wrapped(path,*args,_original=original,_name=name,**kwargs):
                        checked(path,_name);return _original(path,*args,**kwargs)
                    stack.enter_context(mock.patch.object(Path,name,wrapped))
                original_replace=os.replace
                def replace(source,destination,*args,**kwargs):
                    checked(source,"replace");checked(destination,"replace");return original_replace(source,destination,*args,**kwargs)
                stack.enter_context(mock.patch("os.replace",replace))
                original_copy=shutil.copyfile
                def copy(source,destination,*args,**kwargs):
                    checked(source,"copy");checked(destination,"copy");return original_copy(source,destination,*args,**kwargs)
                stack.enter_context(mock.patch("shutil.copyfile",copy))
                jobs=Jobs(directory);sim=dict(count=1,width=2,depth=2,seconds=8,seed=1);bake=dict(resolution=32,normal="OpenGL")
                from test_mask_decoder import png
                mask=base/"mask.png";mask.write_bytes(png(b"\0\xff"))
                first=None
                for rebake in (False,True):
                    request=jobs.prepare(ROOT/"tests/fixtures/cube.obj",sim,bake,rebake=rebake,scatter_mask=mask)
                    logical_request=json.loads(io_path(request).read_bytes())
                    self.assertFalse(logical_request["output_directory"].startswith("\\\\?\\"))
                    process=subprocess.run([str(ROOT/"build/Release/scatter_worker.exe"),str(request)],capture_output=True,text=True,encoding="utf-8",timeout=60)
                    self.assertEqual(process.returncode,0,process.stdout+process.stderr)
                    candidate=jobs.validate(request.parent/"result.json",jobs.active["job_id"]);jobs.promote(candidate)
                    if first is None:first=candidate
                    else:
                        self.assertEqual(first["result"]["poses"],candidate["result"]["poses"])
                        self.assertEqual(first["hashes"],candidate["hashes"])
                        self.assertGreater(max(len(str(p)) for p in io_path(request.parent/"provenance").iterdir()),300)
                    self.assertEqual(jobs.current["job_id"],candidate["job_id"])
                blobs=compat.Blobs();blob_sha=blobs.add(b'{"unchanged_raw_path":"C:\\\\old\\\\path"}')
                save=directory/"manual_blobs";io_path(save).mkdir();blobs.save(save)
                actual=save/"provenance"/(blob_sha+".json")
                self.assertEqual(blobs.read(actual,blob_sha)[0],blob_sha)
                self.assertEqual(digest(actual),hashlib.sha256(blobs.data[blob_sha]).hexdigest())
                self.assertEqual(logical_path(io_path(actual)),logical_path(actual))
                with self.assertRaises(ValueError):compat.local_ref(directory,"../escape.json")
                with self.assertRaises(ValueError):compat.safe_result(directory,"../escape")
                pointer=directory/"current.json";before=digest(pointer)
                with mock.patch("substance_physics_scatter.core.os.replace",side_effect=OSError("promotion failure")):
                    with self.assertRaises(OSError):atomic_json(pointer,{"bad":True})
                self.assertEqual(digest(pointer),before)
            self.assertTrue({"open","stat","mkdir","replace","copy"}.issubset(observed))

if __name__=="__main__":unittest.main(verbosity=2)
