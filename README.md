# Substance Physics Scatter

Designer 16.0.3 / Windows x64용 독립 물리 적층·텍스처 베이크 플러그인입니다.
원본 상용 제품의 소스·그래프·에셋을 사용하지 않는 독자 구현입니다.

## 현재 범위

여러 OBJ(미터, Z-up) → 가중치 선택과 선택적 파일 또는 Graph Scatter Mask → Jolt 5.2.0 Convex Hull 물리 → 정밀 원본 삼각형 BVH 베이크 → Designer Height/Normal/Coverage 출력입니다. Graph 입력은 아래의 검증된 Noise/Invert terminal 구조를 지원합니다. 0.2.1 pose 호환성과 0.3.0 File Mask의 기존 수락 증거도 보존합니다.
물리 엔진과 베이커는 독립 실행 파일에 포함되며 Unreal 또는 MCP를 요구하지 않습니다.
아래 표는 Designer 플러그인의 지원 범위입니다. 별도 로컬 검수 UI의 FBX·PBR·3D·주기 경계 기능과 실행 방법은 [로컬 검수 UI 안내](local_review/README.md)에 있습니다.

| 기능 | 상태 |
| --- | --- |
| OBJ, 낙하·회전·접촉, open/walls, seed | 구현 및 CLI 검증 |
| 최종 pose 캐시와 해상도·노멀 형식 재베이크 | 구현 및 CLI 검증 |
| Height 16bit PNG, DX/GL Normal, Coverage, 2K | 구현 및 수치 검증 |
| Designer 단계 1 핵심·패널 수명·저장/재열기 | 0.1.0 독립 검수 및 실제 앱 PASS, 승인본 보존 |
| 여러 OBJ·확률 가중치·자산별 크기 | 0.2.0 실제 Designer 및 최종 독립 검수 PASS |
| 0.2 pose 캐시 재베이크·최초 origin/직전 source 구분 | 0.2.1 실제 Designer 및 최종 독립 검수 PASS |
| grayscale PNG8/16 파일 Scatter Mask·partial/empty | 0.3.0 실제 Designer 및 최종 독립 검수 PASS, 승인본 보존 |
| FBX·Convex Parts | 후속 단계 |
| Graph Mask | 검증된 Noise/Invert terminal 지원; 실제 Designer 통합 검증 완료 |
| Ground Height | 후속 단계 |
| Base Color/Roughness/Metallic/ID/Random | 후속 단계 |
| 주기 경계 물리·심리스 베이크 | 미구현; tileable 요청을 명시적으로 거부 |
| 실시간 3D 미리보기·8K 검증 | 후속 단계; 현재 Height 이미지 미리보기 |
| SBSAR 게시 및 플러그인 없는 재현 | 후속 검증 |

## 빌드·검증

Visual Studio 2022의 Desktop development with C++와 Windows SDK가 필요합니다.
`powershell -File scripts/build.ps1`은 VS 설치본의 CMake를 찾고 고정 commit의 의존성을 다운로드합니다.
`python -m unittest discover -s tests -p 'test_*.py' -v`는 Pillow와 jsonschema가 설치된 개발용 Python에서 전체 오프라인 검증을 실행합니다. 사용자는 별도 Python/Pillow/jsonschema를 설치할 필요가 없습니다.
`python scripts/package.py`로 `.sdplugin` 및 배포 ZIP을 만듭니다.

## 설치·사용

Designer Tools → Plugin Manager에서 `dist/SubstancePhysicsScatter-0.3.0.sdplugin`을 설치합니다.
현재 버전은 preview이며 Designer 검증 결과는 `output/designer_smoke.json`을 확인하십시오.
저장된 SBS 그래프를 열고 패널의 **Add independent scatter node**를 누릅니다.
**Add OBJ**로 여러 메시를 등록하고 각 파일의 가중치와 크기, 전체 개수·영역·seed를 정한 후 **Simulate + Bake**를 실행합니다.
가중치는 선택 확률입니다. 1:3:6은 장기 비율이며 한 번 실행할 때 정확한 개수를 보장하지 않습니다. 0은 선택에서 제외됩니다.
같은 파일을 서로 다른 가중치·크기로 여러 번 등록할 수 있습니다. 행 순서가 바뀌어도 같은 seed와 설정이면 같은 선택을 사용합니다.
Height/Normal/Coverage 포트를 일반 Designer 노드에 연결해 후보정합니다.
**Use scatter mask**를 켜고 **Choose mask PNG**에서 grayscale PNG8/16을 선택하면 초기 중심 위치의 생성 확률을 조절합니다. 검정은 0%, 흰색은 100%이며 원시 선형 값을 nearest 방식으로 읽습니다. 이미지 위쪽은 +Y, 왼쪽은 -X입니다. 물리 이동 후에는 물체가 Mask 바깥으로 나갈 수 있습니다.
사용한 파일은 결과 폴더에 snapshot으로 보관합니다. 실행 중 입력 컨트롤은 잠기며 파일 선택을 취소하면 기존 선택을 유지합니다. 생성 제한에 도달하면 요청 수보다 적은 정상 결과를 반환할 수 있습니다. 전부 검정이면 정상적인 빈 결과를 저장하며 Height/Coverage는 0, Normal은 (128,128,255)입니다.
해상도나 노멀 형식을 바꿀 때는 **Bake saved pile**을 사용합니다.
물리 설정·메시 파일·가중치·자산 크기·Mask 활성 상태나 파일 내용이 바뀌면 새 시뮬레이션이 필요합니다.
v1 결과와 SBS는 계속 표시합니다. 이전 버전 pose 재베이크는 지원하지 않으며 안내 후 새 작업을 시작하지 않습니다. 새 시뮬레이션이 성공할 때까지 기존 정상 결과를 보존합니다.
여기서 v1은 schema 1입니다. 승인된 0.2.0과 0.2.1의 schema 2 캐시는 원본 request/result chain을 확인할 수 있으면 Mask를 끈 상태에서 재베이크할 수 있습니다. 이전 입력을 새 Mask 형식으로 고쳐 쓰지 않으며 최초 pose와 원본 이력을 보존합니다. 누락·손상·미지원 pose format이면 새 시뮬레이션을 안내하며 기존 이미지를 유지합니다.
패널 작업 후 SBS를 저장해야 그래프와 설정이 저장됩니다.

각 **Add independent scatter node**는 별도 내장 그래프를 생성합니다. 일반 Designer 복제는 동일 서브그래프를 참조할 수 있으므로 독립 배치는 이 버튼으로 생성하십시오.
결과는 `<package>_PhysicsScatter/<scatter-id>/`에 저장됩니다. 파일 경로에 의존하는 재베이크를 위해 SBS와 이 폴더를 함께 보관하십시오.
Designer 16.0.3의 비트맵은 Linked 방식으로 연결합니다. SBS와 결과 폴더를 함께 보관해야 텍스처 출력과 재베이크가 유지됩니다. 사용한 OBJ는 결과 폴더에 해시 기반으로 복사합니다.

## Designer Graph 마스크

직접 검수용 예제를 준비했습니다. `output/GraphMaskReview/latest.json`에 Source.sbs·Scatter.sbs·사용순서.txt의 현재 경로가 있습니다. 첫 결과는 훈위안 brick_red4998삼각형·20개 배치·128px 출력으로 저장됐으며, Designer에는 해당 예제와 소스를 선택해 두었습니다. source/stock 및 Scatter_PhysicsScatter 결과 폴더를 함께 보관합니다.

Designer 패널의 `Graph terminal`에서 소스를 선택하고 `Inspect selected terminal`을 실행한 뒤 `Simulate + Bake`를 누릅니다. Inspector는 계산하지 않습니다. 실행 시 SDK가 원본의 현재 값·타입·연결과 사본을 검증하고, Designer에 포함된 공식 cooker와 Direct3D 11 렌더러가 새 PNG를 생성합니다. Substance 엔진에 `--cpu-count 1`을 명시하며 원본 그래프와 전역 엔진 설정은 바꾸지 않습니다. `Bake saved pile`은 저장된 픽셀과 최종 배치를 재사용합니다. 파일 마스크 체크박스는 `Use file mask`로 구분합니다. 동기 캡처 중의 취소·종료는 반환 후 기존 continuation에서 처리하며 이전 정상 결과를 유지합니다.

현재 Graph 입력은 검증된 Noise/Invert 소스 구조에 한정합니다. 임의의 Designer 그래프 전체를 지원하지 않으며 지원하지 않는 구조는 Inspector에서 거부합니다. 소스와 scatter 대상은 별도 패키지로 둡니다. 실제 검증에 사용한 소스는 `output/designer_graph_ui/95c3882900714807a235a3c32dde1cbe/source/Source.sbs`이며 `stock/` 의존 파일도 함께 보관해야 합니다. 실제 Sim→Saved·취소·metadata rollback·종료 결과와 화면은 같은 실행 폴더의 `report.json`, `graph-ui.png`에 있습니다.

캡처→PNG→소유 캐시→worker의 픽셀 전달은 오차0으로 검증했습니다. 초기 CPU affinity 제한으로 고정32F 복귀·16bit 대조는 통과했지만, 후속 실제 UI 실행 간 역상 대조에서는 773픽셀 차이가 발견됐습니다. 같은 SBS/Direct3D 11에서 엔진 작업 코어 예산16은 차이를 재현했고 예산1은 0이었습니다. OS의 단일 CPU affinity만으로는 엔진 작업 예산1을 보장하지 않으므로, 새 캡처는 검증된 사본만 별도 공식 renderer에 전달해 예산1을 명시합니다. 사본의 dependency filename만 소유한 stock 사본으로 연결하며 다른 authored 바이트는 바꾸지 않습니다. PNG 픽셀 보정·양자화·과거 결과 대체는 하지 않습니다.
수정된 제품 Inspector→Capture의 N/F0/T/F1 전수 대조와 실제 패널의 False/True 물리 계산이 각각262144픽셀에서 오차0입니다. 재베이크·취소·오류 후 이전 정상 결과 유지와 3D 자동 갱신도 검증했습니다. 근거는 `output/evidence/pixel773-final/summary.json`이며 과거773 FAIL과 기각한 대조는 그대로 보존합니다. SDK 트랜잭션의 affinity 복원 guard는 유지합니다. 현재 검증 범위는 Windows·Designer16.0.3·고정된 공식 도구/엔진 SHA이며, 대화형 미리보기 cache와의 비트 동일성이나 다른 플랫폼·GPU 전체의 결정성을 주장하지 않습니다. 도구 불일치·오류·각 자식30초 제한·로그2MiB 초과는 캡처 실패로 처리하고 다른 평가 경로로 fallback하지 않습니다. 새 평가 경로는 capture의 evaluator metadata에 기록합니다. 모듈 갱신 후에는 Graph 소스를 다시 Inspect합니다.

최종 사용 흐름은 `output/designer_bridge/graph-mask-final/750f56d1542545d59d2400185161598e/report.json`에 기록했습니다. Graph 선택·Inspect·시뮬레이션 후 베이크 해상도를64→128로 변경해 물리 재계산 없이 재베이크했고, 대상 SBS 저장·재열기와 원본 Graph 소스 파일이 없는 상태의64 재베이크도 확인했습니다. 최종 위치·회전·최초 origin과64 출력3채널은 최초 결과와 같았습니다. 소스 복원 후 재검사·queued 취소·잘못된 metadata 거부와 rollback에서도 이전 정상 결과가 유지됐습니다. 사용자 패널과 자산은 보존했고 컴퓨터 유즈는 사용하지 않았습니다.

## 제한

- 렌더 메시와 물리 Hull은 다릅니다. 구멍·오목부는 첫 버전에서 막힌 형태로 충돌합니다.
- Height는 상부에서 보이는 2.5D 표면입니다. 아래쪽·오버행·가려진 면은 표현하지 않습니다.
- 높이는 기본 0..2m로 정규화합니다. `clipped_samples`가 0보다 크면 범위를 늘려 재베이크하십시오.
- open 모드는 넓은 유한 평면을 사용합니다. 아주 멀리 흘러간 물체는 바닥 밖으로 떨어질 수 있습니다.
- 첫 버전은 flat triangle normals이며 입력 재질/UV normal map은 아직 처리하지 않습니다.
- 이전 정상 결과와 과거 실행 폴더는 자동 삭제하지 않습니다. 캐시 quota·사용하지 않는 결과 정리 UI는 후속 항목입니다.
- 일반 UI Undo와 플러그인 결과 교체를 통합하는 기능은 아직 구현되지 않았습니다.
- 파일당 256MiB·합계 512MiB, parsed mesh 보관 512MiB, transformed triangle 2m 및 삼각형*256+출력 버퍼 512MiB 작업 예산을 검사합니다. 전체 프로세스 RSS의 상한을 보장하지는 않습니다.
- SHA256은 Windows BCrypt로 실제 읽은 바이트를 확인하며 같은 바이트를 OBJ 파서에 전달합니다. 외부 암호화 라이브러리는 추가하지 않습니다.
- pose provenance는 파일당16MiB·고유 raw bytes 합128MiB·legacy 최대64runs를 검사합니다. 이전 provenance 폴더 전체를 복사하지 않습니다.
- Mask는 파일 64MiB 이하, 각 축 8192 이하, 총 16,777,216픽셀 이하인 비인터레이스 grayscale PNG8/16만 지원합니다. 팔레트·알파·색상 PNG는 거부합니다. 압축 보조 chunk의 내용은 해석하지 않습니다. 디코더는 고정 zlib 1.3.2를 정적 링크하며 PNG 출력 인코더는 기존 LodePNG를 유지합니다.
- worker 버전은 현재 실행을, pose_origin은 최초 생성 기록을 나타냅니다. rebake의 execution은 physics_executed=false/body_count=0/steps=0이며 source_steps는 최초 물리 실행의 단계 수입니다. 호환용 최상위 steps도 source_steps를 유지합니다.

## 패널 수명

패널 초기화는 Designer 세션 registry에서 유효한 dock·panel을 재사용합니다. SDK의 dock identifier는 UUID로 한 번 생성하며, SDK 소유 루트를 직접 close/deleteLater하지 않습니다.
플러그인 종료는 루트를 숨기고 새 실행을 차단한 뒤 자체 워커를 취소합니다. 작업이 끝나면 플러그인 자식만 정리합니다. 동기 대기는 사용하지 않습니다.
Qt QApplication에 둔 QObject registry anchor와 유효성 검사로 모듈 reload 이후에도 같은 dock을 재사용합니다. native 생성 오류는 latch되어 같은 세션에서 자동 재시도하지 않습니다.
`tests/designer_dock_lifecycle.py`는 별도로 명시 실행하는 수명 검증입니다. 테스트 소유의 idle preview에서만 새 고유 dock 최대 1개를 생성하며, 반복 초기화·hide/show·reload 재사용 및 사용자 패키지 불변을 기록합니다. native 오류가 발생하면 즉시 중지합니다.
`tests/designer_dock_shutdown.py`는 이미 존재하는 테스트 소유 dock만 사용합니다. 새 native dock 생성은 mock으로 금지하고, idle 종료·실제 워커 작업 중 비동기 종료·이전 세대 콜백의 격리를 확인합니다. 기존 preview 입력 필드를 복원하고 승인된 테스트 그래프의 metadata·결과 포인터·디코드 픽셀 및 사용자 패키지를 비교합니다. 제한 시간 초과 시 강제 삭제나 새 dock 생성 없이 중단합니다.

## 검증

개발 체크아웃의 플러그인은 로드될 때 로컬 브리지를 자동 시작합니다. 이미 열린 Designer에 구버전 플러그인이 캐시돼 있다면 최초 한 번은 Python Editor에서 저장된 `scripts/start_designer_bridge.py`를 열어 실행해야 새 코드를 로드할 수 있습니다. 이 스크립트는 자동 관리 세션을 명시적으로 시작·재개합니다. 디스크 코드 변경만으로 만료된 구버전 세션이 되살아나는 것은 아닙니다.
이후 터미널에서 `python scripts/designer_request.py health`, `inspect`, `ui_status`, `smoke`, `stop`을 사용합니다. 연결 상태는 `output/designer_bridge/bridge_status.json`에 PID·세션·heartbeat·중지 이유·오류와 함께 기록됩니다. 오래된 파일의 `listening` 표시는 연결 성공의 증거가 아니며 실제 `health` 응답으로 확인합니다.
네트워크를 열지 않으며 요청 파일은 `output/designer_bridge/request.json`만 읽습니다.
요청은 `{ "job_id": "고유영문ID", "operation": "health|inspect|ui_status|smoke|stop" }` 두 필드만 허용하고 코드·경로 인수를 받지 않습니다.
응답은 `responses/<job_id>.json`입니다. 자동 관리 세션은 최대128개 요청 시도 또는1시간 만료 후 처리 중인 요청이 없는 지점에서 새 세션으로 순환합니다. `bridge.start(root)` 수동 호환 API는 기존 한도를 유지합니다. 명시적 `stop`·플러그인 unload·알 수 없는 처리 중 요청·오류는 자동 재실행하지 않으며 원인을 기록합니다. 명시 중지 후 재개하려면 시작 스크립트를 실행합니다. 재사용 ID는 기존 응답을 덮어쓰지 않습니다.
Qt anchor가 같은 Designer 프로세스의 manager·timer를 보존하며, OS 파일 잠금은 같은 체크아웃을 사용하는 새 브리지 프로세스의 동시 소유를 막습니다. 기존 `processing.json`을 발견하면 덮거나 재실행하지 않습니다. 이 자동 시작 기능은 개발 체크아웃의 고정 smoke 경로를 위한 것이며, 개발 파일이 없는 배포 패키지에 범용 코드 실행 기능을 추가하지 않습니다.
크기 제한을 넘거나 symlink인 요청은 `quarantine/`으로 옮긴 뒤 다음 요청을 처리하며 symlink 대상 파일은 읽거나 변경하지 않습니다.
smoke는 별도의 테스트 패널을 생성·정리하고 기존 사용자 패널을 닫거나 선택·편집 상태를 바꾸지 않습니다.
진행 중인 사용자 시뮬레이션이 있으면 smoke를 거부합니다. 테스트용 로컬 opt-in 기능이며 범용 MCP 서버가 아닙니다.

`tests/designer_smoke.py`는 내용이 바뀌지 않는 고정 진입점이며, `designer_smoke_routes.py`가 닫힌 검사 종류를 선택합니다. 기본값은 기존 2A.1 수락과 File Mask 검사를 수행하는 `file_mask`입니다. 검사 전 `python scripts/select_designer_smoke.py <lane>`으로 `output/designer_bridge/smoke_selection.json`만 변경한 뒤 `python scripts/designer_request.py smoke`를 호출합니다. 종류는 selector의 help에 표시되며 코드·파일 경로를 인수로 받지 않습니다. 실행 중에는 선택을 바꾸지 않고, 검사가 끝나면 `python scripts/select_designer_smoke.py file_mask`로 기본값을 복원합니다.
Designer에 열린 진입점 파일을 검사마다 고치거나 과거 backup으로 덮어쓰지 않습니다. 따라서 선택 변경·실행 때문에 이 파일의 Reload 알림이 반복되는 원인을 없앴습니다. 이전 편집으로 이미 떠 있는 알림은 `No`를 한 번 선택하면 됩니다. 화면을 조작하지 않는 검증에서는 알림 창이 실제 닫혔는지까지 확인했다고 보고하지 않습니다.
픽셀·이동·Mask lane helper는 캐시된 모듈을 사용하지 않고 현재 소스에서 고유 모듈로 로드하며 코드 일치 증거를 남깁니다. bridge allowlist와 두 필드 프로토콜은 유지됩니다. 자동 관리로 전환되지 않은 구버전·수동 세션이 만료됐다면 최초 연결을 다시 시작해야 합니다.
두 배치의 모든 출력에 대해 PNG를 디코드해 워커 원본과 비교하고, 재베이크 후 노드 2의 실제 출력 불변·외부 연결의 참조 그래프와 소비자 픽셀·저장/재열기 후 설정·연결·픽셀을 검사합니다.
SDK compute/store 및 결과 승격 실패를 주입하고, 실제 QProcess 취소·강제 종료 뒤 마지막 정상 metadata·픽셀·current.json 보존도 확인합니다.
Designer APIException은 BaseException의 직접 하위 클래스이므로 SDK 예외를 명시적으로 처리하며 KeyboardInterrupt·SystemExit는 삼키지 않습니다.
16.0.3 실증에서 연결의 Input/Output getter 이름과 실제 끝점 방향이 반대로 관찰됐습니다. 지정 그래프에서 목적 노드·입력 포트를 찾고 해당 입력의 연결만 조회한 뒤 정확한 Input/Output category와 포트 ID로 방향을 정규화합니다. 원본 노드와 출력 포트도 같은 그래프에서 다시 조회합니다.
SDK의 opaque `mHandle`은 노드의 영속 identity로 사용하지 않습니다. 노드 ID는 그래프 내부 범위이며, 이 조회 API는 외부 wrapper가 어느 그래프에서 왔는지 전역적으로 증명하는 기능이 아닙니다.
File Mask 테스트는 실행마다 새 `output/designer_file_mask/<고유ID>/PhysicsScatterDemo.sbs`를 만들며 기존 사용자 SBS를 변경하지 않습니다.
Designer 패널의 `Separate window` / `Dock panel`로 같은 패널을 별도 Windows 창으로 이동·복귀할 수 있습니다. 새 Simulate는 일반/PBR/주기 경계 및 Designer Graph 뷰어에 계산 중 실제 낙하·쌓임을 LIVE로 표시합니다. 첫 실제 장면을 준비한 뒤 물리를 시작하며, 고정 dt·RNG·정착 조건과 최종 수치는 유지합니다. 완료 뒤 `Play / Pause / Restart`와 시간 슬라이더로 기록도 재생할 수 있습니다. 사용 방법과 기록 보관 제한은 [로컬 검수 환경](local_review/README.md)을 참조하세요. 실제 LIVE 화면·실행 및 독립 검수 근거는 [최종 기록](output/evidence/realtime-final/summary.json)에 보존합니다.

각 단계의 검증은 전체 제품의 완료를 의미하지 않습니다. 일반 Graph 구조 확장과 clean-install 검증 등 남은 범위는 [구현 계획](docs/implementation-plan.md)에서 추적합니다.
승인된 0.1.0은 `accepted-stage1/`, 0.2.0은 `accepted-stage2A/`, 실제 앱·최종 독립 검수를 통과한 0.2.1은 `accepted-stage2A1/`에 보존했습니다. 0.2.1 계약은 [pose 호환성 계약](docs/pose-compatibility-contract.md)에 있습니다.
0.3.0 승인 후보 `59327fe4`의 배포본·소스·실제 fixture·검수 증거는 `accepted-stage2B-file-mask/`에 복사해 보관했습니다. [최종 독립 검수](output/evidence/final-file-mask-independent-review-59327fe4.json)는 PNG 469개 독립 디코딩, 픽셀 비교 244개, 빈 맵 30개 전체 픽셀 검사와 입력 159개 불변을 확인했습니다. 상세 범위는 [File Mask 인계 문서](docs/file-mask-handoff.md)에 있습니다.
