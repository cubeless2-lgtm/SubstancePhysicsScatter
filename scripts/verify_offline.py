"""Capture offline evidence as UTF-8 without depending on PowerShell redirection encoding."""
from pathlib import Path
import compileall
import json
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"]="utf-8"
EVIDENCE=ROOT/"output/evidence"
EVIDENCE.mkdir(parents=True,exist_ok=True)
cmake=Path("C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe")
build=subprocess.run([str(cmake),"--build","build","--config","Release","--target","scatter_worker","-j","6"],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace")
(EVIDENCE/"file-mask-release-build.txt").write_text(build.stdout+build.stderr,encoding="utf-8")
if build.returncode:raise SystemExit(build.returncode)
compiled=all(compileall.compile_dir(str(ROOT/folder),quiet=1) for folder in ("plugin","tests","scripts"))
for path in (ROOT/"schemas").glob("*.json"):json.loads(path.read_text(encoding="utf-8"))
if not compiled:raise SystemExit("Python compile failed")
process=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_*.py","-v"],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace")
(EVIDENCE/"file-mask-offline-tests.txt").write_text(process.stdout+process.stderr,encoding="utf-8")
print(process.stdout+process.stderr)
if process.returncode:raise SystemExit(process.returncode)
for script in ("package.py","verify_package.py","check_mask_dependencies.py"):
    process=subprocess.run([sys.executable,str(ROOT/"scripts"/script)],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace")
    mode="w" if script=="package.py" else "a"
    with (EVIDENCE/"file-mask-package.txt").open(mode,encoding="utf-8") as stream:stream.write(process.stdout+process.stderr)
    print(process.stdout+process.stderr)
    if process.returncode:raise SystemExit(process.returncode)
