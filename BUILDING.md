# Windows에서 소스 빌드 및 실행

Windows x64, Visual Studio 2022의 C++ 데스크톱 개발 도구와 Windows SDK, CMake, Python 3.11, Node.js/npm, Blender 5.2가 필요합니다. CMake는 고정된 외부 라이브러리 소스를 인터넷에서 다운로드합니다.

저장소 루트의 PowerShell에서 다음을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_all.ps1
python -m venv local_review/.venv
& local_review/.venv/Scripts/python.exe -m pip install -r local_review/requirements.lock
npm ci --prefix local_review
& local_review/.venv/Scripts/python.exe scripts/register_local_workers.py
& local_review/.venv/Scripts/python.exe local_review/launch.py --source
```

브라우저에서 http://127.0.0.1:8765/ 를 엽니다. Blender가 기본 위치에 없으면 실행 전에 `$env:SCATTER_BLENDER`에 blender.exe의 전체 경로를 지정합니다. 포트는 `launch.py --source --port 8766`처럼 바꿀 수 있습니다.

워커 등록은 이 PC에서 사용자가 빌드한 실행 파일을 로컬에서 신뢰하도록 설정합니다. fingerprint와 실행 파일 해시를 기록해 이후 변경을 감지하지만, 해당 바이너리가 소스에서 만들어졌다는 독립적인 증명은 아닙니다. 다시 빌드했다면 등록을 다시 실행하세요. 등록과 작업 결과는 Git에 포함되지 않습니다.

훈위안 자산과 Designer 예제, 기존 결과는 저장소에 포함되지 않습니다. 직접 OBJ/FBX 및 필요한 텍스처를 가져와 사용하세요. Designer 연동에는 별도로 호환되는 Substance 3D Designer 설치가 필요합니다.
