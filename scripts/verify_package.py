from pathlib import Path
import json
import hashlib
import subprocess
import tempfile
import zipfile
import sys
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="scatter_packaged ") as temp:
    base=Path(temp)
    with zipfile.ZipFile(ROOT/"dist/SubstancePhysicsScatter-0.3.0.sdplugin") as z:
        assert "licenses/zlib-LICENSE" in z.namelist()
        z.extractall(base)
    mesh=base/"cube.obj";mesh.write_bytes((ROOT/"tests/fixtures/cube.obj").read_bytes())
    pyramid=base/"pyramid.obj";pyramid.write_bytes((ROOT/"tests/fixtures/pyramid.obj").read_bytes())
    rows=[{"asset_id":"0000000000004000800000000000000"+str(index),"path":str(path),"content_hash":hashlib.sha256(path.read_bytes()).hexdigest(),"format":"obj","scale":.25,"weight":1} for index,path in enumerate((mesh,pyramid),1)]
    sys.path.insert(0,str(base))
    from substance_physics_scatter.core import Jobs
    jobs=Jobs(base/"result");path=jobs.prepare(rows,{"count":20,"seconds":8,"seed":123456789},{"resolution":64})
    process=subprocess.run([str(base/"substance_physics_scatter/bin/scatter_worker.exe"),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=60)
    if process.returncode:raise RuntimeError(process.stdout+process.stderr)
    result=json.loads((path.parent/"result.json").read_text(encoding="utf-8"))
    assert result["engine"]=="Jolt 5.2.0" and result["status"]=="completed"
    assert {p["asset_id"] for p in result["poses"]}=={a["asset_id"] for a in rows}
    assert all((path.parent/(name+".png")).is_file() for name in ("height","normal","coverage"))
    # Run the decoder and empty output path from the extracted package as well.
    import struct,zlib
    def chunk(kind,data):return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    mask=base/"black.png";mask.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",1,1,16,0,0,0,0))+chunk(b"IDAT",zlib.compress(b"\0\0\0"))+chunk(b"IEND",b""))
    empty_jobs=Jobs(base/"empty");path=empty_jobs.prepare(rows,{"count":20},{"resolution":64},scatter_mask=mask)
    process=subprocess.run([str(base/"substance_physics_scatter/bin/scatter_worker.exe"),str(path)],capture_output=True,text=True,encoding="utf-8",timeout=60)
    assert process.returncode==0,process.stdout+process.stderr
    empty=empty_jobs.validate(path.parent/"result.json",empty_jobs.active["job_id"])
    assert empty["result"]["poses"]==[] and empty["result"]["spawn_stop_reason"]=="all_black"
    assert empty["result"]["worker_version"]=="0.3.0"
    print("PASS: extracted package worker runs without source/build directories or external DLLs")
