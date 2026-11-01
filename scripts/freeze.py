"""Freeze authored sources, dependencies, archived test inputs and runnable distribution."""
from pathlib import Path
import hashlib
import json
import platform
ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
files={}
for folder in ("worker","plugin","tests","schemas","scripts","docs","third_party","accepted-stage2A/fixtures","accepted-stage2A1/fixtures"):
    for path in (ROOT/folder).rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            files[path.relative_to(ROOT).as_posix()]=sha(path)
for name in ("accepted-stage1/scatter_worker.exe","accepted-stage1/candidate.json","accepted-stage2A1/scatter_worker.exe","accepted-stage2A1/candidate-pose-compat.json","accepted-stage2A1/archive-evidence.json","CMakeLists.txt","README.md",".gitignore","build/Release/scatter_worker.exe","dist/SubstancePhysicsScatter-0.3.0.sdplugin","dist/SubstancePhysicsScatter-0.3.0.zip","build/downloads/zlib-1.3.2.tar.gz","build/_deps/lodepng-src/lodepng.h","build/_deps/lodepng-src/lodepng.cpp"):
    files[name]=sha(ROOT/name)
identity=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
manifest={"candidate_sha256":identity,"files":files,"environment":{"platform":platform.platform(),"python":platform.python_version(),"designer_target":"16.0.3","MSVC":"19.38.33145.0","Jolt":"5.2.0","SHA256":"Windows BCrypt"},"verification":{"offline_tests":"output/evidence/stage2-offline-tests.txt","package":"output/evidence/stage2-package.txt","designer_smoke":"Stage2A candidate NOT EXECUTED. Parent owns actual Designer lane tests/designer_smoke.py -> designer_stage2.py.","claim":"stage2A candidate; independent review and Designer live remain required"},"accepted_stage1":{"candidate":"8ebb02fe3beee81cd0110155661186b19025a676f50a0657417dc7df37b1442c","archive":"accepted-stage1"}}
manifest["verification"]={"offline_tests":"output/evidence/file-mask-offline-tests.txt","package":"output/evidence/file-mask-package.txt","build":"output/evidence/file-mask-release-build.txt","supplement":"output/evidence/file-mask-dependency-check.json","designer_smoke":"NOT EXECUTED: parent owns tests/designer_smoke.py -> designer_file_mask.py -> fresh designer_acceptance.py + designer_file_mask_lane.py","acceptance_map":"docs/file-mask-handoff.md","claim":"File Mask candidate; independent review and actual Designer acceptance remain required"}
manifest["environment"]["zlib"]="1.3.2 static /MT"
manifest["accepted_stage2A"]={"candidate":"a39e7a27ba134da22b3d43fec53f7d804c03c219ce03a4167675ba79e3ab5a5d","archive":"accepted-stage2A"}
manifest["accepted_stage2A1"]={"candidate":"63eeb99ad9a37672c9b39ed9a85b7b4b08a75806ad19b7fa720152efb0e355e2","archive":"accepted-stage2A1","archive_evidence_sha256":sha(ROOT/"accepted-stage2A1/archive-evidence.json")}
out=ROOT/"output/evidence/candidate-file-mask.json";out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
print(identity)
