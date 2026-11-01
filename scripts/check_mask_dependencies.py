"""Read-only dependency/protected-code checks, plus a new evidence JSON."""
from pathlib import Path
import hashlib,json,re,subprocess,tarfile,zipfile
ROOT=Path(__file__).resolve().parents[1]
def sha(data):return hashlib.sha256(data).hexdigest()
archive=ROOT/"build/downloads/zlib-1.3.2.tar.gz";expected="bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16"
assert sha(archive.read_bytes())==expected
with tarfile.open(archive) as z:assert z.extractfile("zlib-1.3.2/LICENSE").read()==(ROOT/"third_party/zlib-LICENSE").read_bytes()
protected={}
with zipfile.ZipFile(ROOT/"accepted-stage2A1/SubstancePhysicsScatter-0.2.1-source.zip") as z:
    for name in ("__init__.py","lifecycle.py","connections.py","bridge.py"):
        path="plugin/substance_physics_scatter/"+name
        assert z.read(path)==(ROOT/path).read_bytes(),path
        protected[path]=sha(z.read(path))
    def encoder(data):
        text=data.decode("utf-8");return text[text.index("static void writePNG("):text.index("static json bake(")]
    assert encoder(z.read("worker/main.cpp"))==encoder((ROOT/"worker/main.cpp").read_bytes())
    pinned=json.loads(z.read("third_party/dependencies.json"))["lodepng"]
    assert json.loads((ROOT/"third_party/dependencies.json").read_bytes())["lodepng"]==pinned
project=(ROOT/"build/_deps/zlib-build/zlibstatic.vcxproj").read_text(encoding="utf-8")
assert "<ConfigurationType>StaticLibrary</ConfigurationType>" in project and "<RuntimeLibrary>MultiThreaded</RuntimeLibrary>" in project
dumpbin=Path("C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Tools/MSVC/14.38.33130/bin/Hostx64/x64/dumpbin.exe")
p=subprocess.run([str(dumpbin),"/dependents",str(ROOT/"build/Release/scatter_worker.exe")],capture_output=True,text=True,encoding="utf-8",errors="replace")
assert p.returncode==0,p.stdout+p.stderr
assert not re.search(r"\b(?:zlib[^\s]*|vcruntime[^\s]*|msvcp[^\s]*)\.dll\b",p.stdout,re.I),p.stdout
preserved={}
for version in ("accepted-stage1","accepted-stage2A","accepted-stage2A1"):
    preserved[version]={str(path.relative_to(ROOT/version)):sha(path.read_bytes()) for path in (ROOT/version).rglob("*") if path.is_file()}
old=json.loads((ROOT/"accepted-stage2A1/archive-evidence.json").read_bytes())
for path,value in old["artifact_sha256"].items():assert sha((ROOT/"accepted-stage2A1"/path).read_bytes())==value
out=dict(status="pass",zlib_archive_sha256=expected,zlib_license_matches_official_archive=True,static_library_and_CRT=True,protected_files_unchanged_from_approved021=protected,lodepng_pin_unchanged=True,lodepng_encoder_function_exact=True,worker_dependencies=p.stdout,accepted_archives_read_only_sha256=preserved)
(ROOT/"output/evidence/file-mask-dependency-check.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print("PASS: archive SHA/license, static CRT/linkage, approved lifecycle/connections/bridge/encoder and archive hashes")
