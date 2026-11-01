"""Build a self-contained Designer .sdplugin archive and matching distribution ZIP."""
from pathlib import Path
import json
import shutil
import zipfile
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"dist";out.mkdir(exist_ok=True)
worker=ROOT/"build/Release/scatter_worker.exe"
if not worker.is_file():raise SystemExit("Build worker first")
with zipfile.ZipFile(out/"SubstancePhysicsScatter-0.3.0.sdplugin","w",zipfile.ZIP_DEFLATED) as z:
    z.write(ROOT/"plugin/pluginInfo.json","pluginInfo.json")
    for path in (ROOT/"plugin/substance_physics_scatter").rglob("*.py"):
        z.write(path,path.relative_to(ROOT/"plugin").as_posix())
    z.write(worker,"substance_physics_scatter/bin/scatter_worker.exe")
    for source,name in (("jolt-src/LICENSE","Jolt-LICENSE"),("json-src/LICENSE.MIT","json-LICENSE"),("tinyobj-src/LICENSE","tinyobj-LICENSE"),("lodepng-src/lodepng.h","lodepng-NOTICE-source")):
        z.write(ROOT/"build/_deps"/source,"licenses/"+name)
    z.write(ROOT/"third_party/zlib-LICENSE","licenses/zlib-LICENSE")
    z.write(ROOT/"third_party/dependencies.json","licenses/dependencies.json")
with zipfile.ZipFile(out/"SubstancePhysicsScatter-0.3.0.zip","w",zipfile.ZIP_DEFLATED) as z:
    z.write(out/"SubstancePhysicsScatter-0.3.0.sdplugin","SubstancePhysicsScatter-0.3.0.sdplugin")
    z.write(ROOT/"README.md","README.md")
print(out)
