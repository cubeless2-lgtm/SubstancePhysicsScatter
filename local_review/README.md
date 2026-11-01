# Scatter Local Review · UI/PBR 및 실제 주기 경계 검수

로컬 OBJ/FBX, 원본 PBR 재질, 실제 물리 배치·충돌 Hull과 7개 베이크 출력을 검사합니다. 기존 계산·Designer 연동을 재사용하며, 주기 경계는 별도 N3 worker와 명시적인 input3 규약으로 연결합니다.

```powershell
$env:SCATTER_REVIEW_PORT='8765'
& D:/Git/SubstancePhysicsScatter/local_review/.venv/Scripts/python.exe -u -B -m uvicorn server:app --app-dir D:/Git/SubstancePhysicsScatter/local_review --host 127.0.0.1 --port 8765 --no-access-log
```

위 명령은 현재 실제 실행을 검증한 개발 실행 방법입니다. 브라우저 주소는 `http://127.0.0.1:8765`입니다. 이전 UI3A 후보를 고정한 `launch.py`의 source manifest는 현재 구현의 수락 증거가 아닙니다. loopback·동일 Host/Origin·세션 토큰·단일 작업·실제 worker identity·출력 검증과 마지막 정상 결과 보존 경계는 유지합니다. 외부 CDN이나 Node 서버가 필요하지 않습니다.

빠른 검수: **실제 Hunyuan 6종 선택 → 저장 배치 설정 불러오기 → 가장자리 Walls/Open/Periodic 선택 → Simulate → 최종 배치/Actual Hull/3×3/Baked Surface → Saved 재베이크 → 결과 ZIP 내려받기** 순서로 사용할 수 있습니다. 카메라는 드래그와 휠로 조작하고 전체 보기·선택 보기를 지원합니다. Hunyuan 벽돌3종·돌3종은 각각 4,998 triangles이며 512² BC/R/M을 사용합니다. 이 6종에는 원본 normal map이 없어 geometric fallback을 사용합니다. 수동 normal 연결은 별도로 검증했습니다.

새 `Simulate`는 일반/PBR/주기 경계 및 Designer Graph 뷰어에 **계산 중 실제 낙하·쌓임을 LIVE로 표시**합니다. 메시·재질·첫 실제 장면을 준비한 뒤 뷰어가 준비 신호를 보내면 물리 계산이 시작됩니다. 준비 대기는 최대8초이고 초과 시 경고를 표시합니다. 실시간 보기에서는 실제 시간에 맞춰 진행하며 고정 물리 dt·RNG·정착 조건은 바꾸지 않습니다. 실제 관측 위치·회전만 표시하고 보간하거나 가짜 낙하를 만들지 않습니다. LIVE 지도는 이전 정상 결과임을 표시하고, 새 배치·베이크는 검증·승격이 끝난 뒤 교체합니다. 취소·실패 시 이전 정상 장면을 복원합니다. 최신 프레임은 job의 `live-frame-v1.json` 하나로 교체하며, 완료 증거로 사용하지 않습니다.

완료 뒤에는 `Play / Pause / Restart`, 시간 슬라이더와 `최종 배치로 보기`로 기록도 재생할 수 있습니다. 마지막 프레임은 최종 pose와 정확히 같습니다. Saved는 원래 Sim 기록을 재사용하며 새 물리를 실행하지 않습니다. 이전 결과에는 `기록 없음 · 새 Simulate 필요`를 표시합니다. 원본/베이크 표면은 최종 검수이고 LIVE 중에는 최종 Hull과 완료 결과 재생을 숨기거나 일시 정지합니다. 완료 기록은 job의 `motion-v1.json`에 최대8MiB·40,000개 pose·3,601프레임으로 보존합니다. 현재 ZIP 내보내기는 Saved의 외부 Sim 기록까지 함께 묶지 않습니다. 실제 LIVE 화면·실행·독립 검수 근거는 `../output/evidence/realtime-final/summary.json`입니다.

Designer 패널 상단 `Separate window`는 동일 패널을 독립 Windows 창으로 옮깁니다. 제목줄로 이동하고 테두리 또는 Windows 기본 크기 조절 메뉴로 조절합니다. 작은 창에서는 내부를 스크롤합니다. `Dock panel`로 복귀하며 X/Escape는 숨김만 수행합니다. 다시 열 때는 Designer `Windows → Physics Scatter`를 선택합니다. 계산 중에는 분리·복귀를 거부하고 진행 중인 작업과 이전 결과를 유지합니다.

준비된 **Designer Graph 마스크 예제**는 첫 화면의 `Designer Graph 예제` 링크 또는 `http://127.0.0.1:8765/designer-review/?view=pile`에서 확인합니다. `원본 OBJ → 실제 최종 배치 → 베이크 3D 표면`을 전환하고 드래그·휠·전체 보기·Wire를 사용합니다. 아래 Height16 / Normal / Coverage 이미지를 클릭하면 원래 픽셀 값을 확인하고 `원본 PNG`로 저장할 수 있습니다. 첫 결과는 job `169d87df7d034f7f8f5fa6d32f918020`의 실제 배치20개·원본 OBJ4,998삼각형·128² H/N/C이며, 이후 새 정상 계산도 자동 반영합니다. 정상 로컬 결과와 자산 목록을 바꾸거나 뷰어 자체에서 새 계산을 실행하지 않습니다. PBR·Actual Hull·주기 경계 데이터는 이 Designer 예제에 없습니다.

예제 데이터는 `workspace/designer-review/<job_id>`에 별도로 보관됩니다. 뷰어를 열어 두고 Designer에서 **Graph 변경 → Inspect selected terminal → Simulate + Bake**를 실행하면 새 정상 결과를 약 2초 간격으로 확인합니다. `Bake saved pile`로 만든 새 베이크도 반영합니다. 검증한 배치·형상·PNG·Height16를 새 immutable snapshot에 보관하고 마지막에 포인터를 교체합니다. 브라우저도 현재 모드의 3D 데이터와 지도 3개를 모두 불러온 후 교체하므로 채널이 다른 계산과 섞이지 않습니다. 카메라는 유지하며 `전체 보기`로 다시 맞출 수 있습니다.

계산 실패·취소나 새 결과 검증/로딩 실패 시 마지막 정상 배치와 베이크를 유지하고, 화면 아래에 현재 표시 중인 Job과 동기화 오류를 구분합니다. 실패한 동일 입력의 복사를 반복하지 않으며, 변경된 결과가 발견되면 다시 검사합니다. 숨겨진 탭은 확인을 멈추고 복귀하면 재개합니다. 원본 Graph의 미계산 수정은 새 배치로 표시하지 않습니다. 기존 snapshot과 원본 출력은 덮어쓰지 않으며, 일반 로컬 뷰어의 current와 자산 목록에도 영향을 주지 않습니다. 현재 지원 범위는 지정된 Graph 예제 대상의 입력2·단일 OBJ·H/N/C 결과이며 PBR·Actual Hull은 추가하지 않습니다. 서버 재실행은 위 uvicorn 명령을 사용합니다. 기존 고정 결과의 검증 근거는 `../output/evidence/designer-viewer-connection-20261101/`에 보존합니다.

초기 자동 갱신 검증은 `../output/evidence/designer-viewer-live-20261101/summary.json`에 보존합니다. 당시 발견한 실행 간 역상773픽셀 차이는 엔진 작업 예산을 명시하는 캡처로 수정했습니다. Designer의 검증된 현재 그래프 사본을 공식 Direct3D 11 renderer에 `--cpu-count 1`로 전달하며 대화형 preview cache를 사용하지 않습니다. 수정 후 제품 N/F0/T/F1과 실제 패널 False/True 마스크는 각262144픽셀에서 오차0이고, Saved256·오류/취소 보존·3D 자동 교체도 통과했습니다. 새 근거는 `../output/evidence/pixel773-final/summary.json`입니다. 과거 FAIL은 변경하지 않았고, 픽셀 후처리·허용 오차 증가는 없습니다. 현재 연결은 OpenGL Normal과 64~2048px 출력을 지원하며 미지원 결과나 실패 시 이전 정상 결과를 유지합니다.

OBJ/FBX 한 모델과 평면 외부 텍스처/MTL bundle을 선택하거나 drop합니다. FBX는 embedded 이미지도 추출하되 임의 외부 경로를 열지 않습니다. FBX metadata 자동 변환 또는 사용자 단위·축 override 중 하나만 적용합니다. hierarchy의 world transform과 mirrored winding을 canonical geometry에 적용하고, group 또는 part별 split으로 가져옵니다. 각 part는 1..4999 triangles이며 실행 선택은 weight0도 포함해 최대6개입니다.

원본 재질의 BaseColor/Roughness/Metallic/normal 역할을 확인하고, 소유한 이미지·packed R/G/B channel·색공간·UV wrap·DX/GL을 직접 지정할 수 있습니다. 역할별 이미지 datablock을 분리해 BC의 sRGB와 data map의 Non-Color가 충돌하지 않게 합니다. canonical 텍스처는 **원본512² 불투명 이미지의 RGBA8 PNG derivative**입니다. 크기 재샘플링은 하지 않으며 JPEG decode를 무손실 원본 복원이라고 부르지 않습니다. DX normal의 표시용 G 반전 copy는 canonical 원본과 분리합니다. normal map이 없으면 geometric fallback입니다. 지원하지 못한 procedural shader/UV/tangent는 geometry 모드의 경고로 표시하고 N2-ready로 주장하지 않습니다.

Blender5.2.0 LTS의 `--background --factory-startup --disable-autoexec` 변환에서 동일한 삼각 corner geometry를 physics OBJ·GLB·corner JSON으로 내보냅니다. RH_Z_UP·미터를 사용하며 display-up 변환과 pose scale은 각각 한 번만 적용합니다. geometry 재가져오기는 새 derivative ID를 만들고 원본을 보존합니다. 재질 factor·추가 텍스처·채널 연결은 같은 geometry ID로 갱신합니다. 정상 배치는 고정된 GLB와 render/material revision을 사용하므로 catalog 변경 시 이전 결과임을 표시합니다. Saved는 기존 pose·Mask로 최신 재질과 베이크 설정만 계산하며 물리 설정 변경은 거부합니다.

Material/Solid/Wire 모드와 Actual Hull을 제공합니다. 실제 Jolt `Create`의 scaled-origin-local hull·COM·scale·producer를 검증하며 pose scale을 다시 곱하지 않습니다. single convex collider이므로 원본 mesh와 다를 수 있습니다. Saved는 검증된 실제 Simulate Hull을 이어받고, 그 원본 근거가 없어지거나 오염되면 Hull 표시를 해제합니다. 실제 브라우저·OBJ/FBX·원본 재질·재베이크·ZIP·실패/취소·재시작 검증과 묶음 독립 검수가 완료됐습니다.

Height·Geometric Normal·Coverage·BaseColor·Roughness·Metallic·Material Normal을 제공합니다. 준비된 재질의 7개 채널은 같은 최고 표면 Hit를 사용합니다. walls/open은 검증된 N2, periodic은 N3를 사용합니다. 입력 OBJ/FBX·MTL·텍스처와 파생 데이터는 변경하지 않고 보관하며 ZIP에는 출력·pose·설정·자산·텍스처·출처를 포함합니다. ZIP 가져오기/자동 복원은 지원하지 않습니다. 원본 경로가 없으면 현재 job에 보관된 동일 revision으로 미리보기·재질 편집·Saved를 연결하고, geometry 재가져오기는 원래 파일이 필요하다고 안내합니다.

Python3.11 격리 `.venv`·FastAPI0.162.0·Three0.187.0·Pillow 등 정확한 버전은 기존 lock과 설치 파일 SHA로 고정합니다. 실제 Blender는 `C:/Program Files/Blender Foundation/Blender 5.2/blender.exe`입니다. bundle20파일/128MiB/파일32MiB, canonical texture512²·최대64개, corner8MiB, GLB64MiB, workspace2GiB 및 자기 child120초/로그4MiB 제한을 둡니다. 이 readback 제한은 native write/RSS hard cap이 아닙니다. animation/skin/deformer, 투명 재질·임의 shader·workspace 이동은 지원 범위가 아닙니다.

준비 검사: `.venv/Scripts/python.exe -B -m unittest test_local test_ui2 -q`, `node --check web/app.js`, `node --check web/ui2.js`. Builder는 순수/ASGI/fake child 검사만 수행하며 실제 Blender·worker·브라우저 실행은 coordinator 소유입니다.


## 저장과 표시 경계

실제 Hunyuan6종 선택 버튼은 canonical6 ID와 원본/final_clean 자료를 검증하고 선택만 바꿉니다. 누락되거나 자료가 바뀌면 오류를 표시하며 등록된 수동 텍스처도 구분합니다. 원본/library/runtime record를 자동 수정하지 않습니다. 모든 선택 자산이 material-ready이면 7개 출력을 같은 최고Hit에서 계산합니다. walls/open에서 재질 미완료 자산을 포함하면 geometry-only로 처리하고 PBR 탭을 비활성화합니다. periodic은 준비된 UV/PBR 자산이 필요합니다.

새 실행은 물리 OBJ·corner·사용 텍스처·원본 파일·GLB를 새 job-owned closure에 복사하고 원본/사본 SHA를 대조합니다. manifest와 실제 producer/sidecar/출력 검증 후에만 current를 승격합니다. 이후 표시에는 저장된 job GLB를 사용합니다. 검증 결과는 cache에 두되 raw SHA가 달라지면 제공을 중단하며, inherited Hull만의 출처 문제는 명시적인 Hull 없음으로 표시합니다. worker의 실제 오류도 화면에 전달합니다.

Height16은 grayscale16 PNG를 uint16 LE로 전송하며 canvas8bit로 읽지 않습니다. Baked Surface는 LOD129/257/513을 선택합니다. walls/open은 기존 nearest-source를, periodic은 원본 픽셀 중심의 Repeat/bilinear 재구성을 사용합니다. 원본 PNG의 가장자리 픽셀을 복사·평균하여 맞추지 않습니다. PNG row0은 canonical+Y입니다. normal은 ObjectSpaceNormalMap으로 적용하고 DX 표시용 G 반전은 한 번만 수행합니다. 이 표면은 2.5D heightfield이므로 높이 불연속의 skirt와 원본 mesh 측면을 완전히 재현하지 못하는 한계가 있습니다. 화면의 조명/tone mapping 색과 지도 원본 수치는 구분합니다.

**Periodic은 실제 주기 경계 모드입니다.** 반대편·모서리 이웃의 충돌을 같은 실제 body에 적용하며 ghost body나 질량을 추가하지 않습니다. 중앙 베이크는 render AABB로 필요한 이웃 이미지를 열거하고 7개 채널에 같은 가시성을 적용합니다. 실제 body60/화면3×3표시540을 구분합니다. 제품 periodic는 허용된 최대16분할을 사용하고, 변위 L/64·크기·예산을 초과하는 입력은 명시적으로 실패합니다. walls/open의3×3는 표시 반복입니다.

최종 실제 결과와 화면: `../output/evidence/ui3b-integrated-results-20261101.json`, `../output/evidence/periodic-P2-integrated-results-20261101.json`, `../output/evidence/periodic-final-3x3-material-20261101.jpg`, `../output/evidence/periodic-final-3x3-baked-20261101.jpg`. 기존 PASS는 재사용하고 변경 경로를 집중 검증했습니다. 5개 중앙 베이크 시험의143,360 channel pixels는 오차0입니다. 이전 native 실패2건과 과거 Designer 수학 FAIL은 원문으로 보존합니다. 이후 Designer 평가 범위 수정으로 원래 픽셀 기준을 오차0으로 통과했고, 검증된 Noise/Invert Graph Mask의 전체 사용 흐름도 `../output/designer_bridge/graph-mask-final/750f56d1542545d59d2400185161598e/report.json`에서 완료했습니다. 상세 사용법과 범위는 루트 README의 Designer Graph 마스크 절을 따릅니다.
