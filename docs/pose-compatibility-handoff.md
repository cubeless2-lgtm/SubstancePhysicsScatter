# 0.2.1 pose 호환성 후보 인계

제품 writer와 CLI 실행은 builder가 소유했고 실제 Designer는 실행하지 않았습니다. connections/lifecycle/SDK root와 승인 accepted-stage1·accepted-stage2A 보관본은 유지했습니다. 새 실제 0.2 fixture 31개 파일 354102bytes만 accepted-stage2A/fixtures에 복사하고 전후 SHA를 확인했습니다.

## 구조

compat.py는 입력 기본값·strict normalization·exact JSON bytes·physics_input_v1 key·immutable 원본·legacy chain을 담당합니다. worker/compatibility.h는 같은 파일 bytes의 SHA와 파싱 결과, role/identity/chain/envelope를 독립 검증합니다. C++ serializer로 Python key를 재현하지 않습니다.
물리·삼각형 베이크 계산 수식은 유지했습니다. 원본 pose를 변경하던 정규화는 깊은 계산용 복사본으로 옮겼으며, provenance와 최종 result는 원래 숫자와 배열 순서를 유지합니다. 최초 origin record와 현재 실행·직전 입력 source를 별도로 기록합니다.
host가 지원되는 원본 physics_inputs raw bytes를 재사용하고, 경로·표시 이름·행 순서·worker/bake 버전을 physics identity에서 제외합니다. rebake key는 최초 key/scheme/physics contract로 유지합니다. physics contract가 다른 synthetic protocol fixture를 수용하는 것은 실제 미래 엔진 검증을 뜻하지 않습니다.
legacy는 0.2.0 순수 schema2만 허용합니다. 최초 Sim까지 원본 request/result를 추적하며, legacy key-material raw bytes와 SHA를 보존합니다. 최대64runs, 파일당16MiB, 작업당 고유 raw bytes128MiB이며 blob SHA가 같아도 사용 role·job·asset·sim·pose·좌표·단위를 확인합니다. 이전 provenance 폴더 전체를 복사하지 않습니다.
실행 경로는 검증한 owned run ID/contenthash로만 재해석합니다. 이동 fixture는 current.json/SBS metadata의 runtime pointer만 변경하고 immutable request/result/origin/input/pose_source/blob은 byte-identical하게 보존합니다.

## 검증과 native 경로 이슈

Release worker, 전체 offline, Python compileall/schema 파싱, 0.2.1 ZIP/sdplugin 생성 및 추출 패키지 실행을 검증합니다. 로그는 output/evidence/pose-compat-offline-tests.txt와 pose-compat-package.txt입니다.
첫 검수 전 후보의 전체 offline 결과는54개 중53 PASS, 기존 Windows symlink 권한1 skip이었습니다. archive fingerprint 항목은 실행에 쓰는 accepted-stage2A/fixtures 전체와 v1 worker/승인 manifest입니다. 이 입력들은 후보 manifest와 Designer pre/post fingerprint에 포함하며 보관본 자체는 변경하지 않습니다.
실제 승인된 0.2 Sim과 이미 재베이크된 current의 연속2회 rebake에서 pose·모든 decoded PNG·형식을 비교합니다. 현재 worker/execution(false/0/0), 최초 origin, 직전 source를 구분합니다. 신규 Sim·연속 rebake·raw 비단위 quaternion·지원 JSON 공백 차이·synthetic physics contract 차이도 포함합니다.
손상·unknown/partial format·단위·원본 request 누락·순환·이탈·64/65 경계·role 충돌·실제16MiB/128MiB 초과 및 lastgood을 검사합니다. 실제128MiB native 음성 fixture를 만들 때만 test mock으로 host 한도를 올리며 제품 한도는 바꾸지 않습니다.
초기 native 종료는 긴 첫 provenance 경로의 fs::file_size 경계에서 0xc0000409로 재현됐습니다. 짧은 경로는 성공했으며, 현재 모든 native request/OBJ/PNG/origin/result/provenance I/O와 원자 rename에 Windows 확장 경로를 적용했습니다. 기존 격리 자료는 output/compat_native/be7ac29a에 보존했습니다. 정확한 CRT 내부 종료 원인은 단정하지 않습니다.
회귀는 경로를 줄이지 않습니다. archive 복사본의 provenance 경로가260자를 초과함을 assert하고, 캐시 root 자체270자 이상/한글 경로에서 실제 Sim→rebake를 검사합니다.

## 실제 앱 인계와 제한

고정 tests/designer_smoke.py는 designer_pose_compat.py를 호출합니다. 최신 compat/core/designer/UI는 수용 lane에서 다시 읽고 기존 사용자 preview/SDK root는 재생성하지 않습니다. 기존 bridge는 변경하지 않았으므로 활성 상태라면 재시작할 필요가 없습니다.
lane은 기존 두 유형 Sim/rebake·후처리 연결·모든 decoded output·실패 rollback·cancel/crash·save-reopen·이동·v1 차단에 실제 approved0.2 두 유형의 연속 rebake와 moved legacy chain을 추가합니다. immutable JSON hash와 origin/execution을 검사합니다. package load가 다른 기존 package로 해석되거나 pre-relink export가 다르면 우회하지 않고 실패합니다.
이번 후보의 실제 Designer 결과는 아직 없습니다. 부모의 실행과 독립 검수 후에 수락할 수 있습니다. Mask/physics/bake 확장, arbitrary absolute Linked 경로 복원, 미래 엔진 검증은 이번 범위가 아닙니다.

## 5239f2e2 독립 검수 지적에 대한 수정

검수 자료는 output/evidence/review-pose-compat-5239f2e2에 보존합니다. 수정 범위는 다음 세 결함으로 한정했습니다.

- 일반 이동과 legacy 이동이 WORK/migration을 공유하던 충돌을 별도 WORK/legacy_migration namespace로 분리했습니다. 실제 lane의 두 호출 구성을 AST에서 읽어 실행 순서대로 파일 fixture를 만드는 회귀를 추가했습니다.
- 모든 허용 float의-0.0을+0.0으로 정규화합니다. friction/restitution의 bytes/hash/key 동일성과 native semantic 수용을 검사하며, 과거 raw 음의0을 포함한 input/origin의 bytes/key는 재베이크 때 그대로 보존합니다.
- host/native가 steps/body_count의 정확한 정수 타입·비음수·상호 일치를 검사합니다. 신규 Sim은 네 steps가 같고 body 수가 pose 수와 일치해야 합니다. rebake는 execution만 false/0/0이며 result.steps/source_steps는 최초 origin과 같습니다. settling도 최초 origin·legacy chain·직전 소비 bundle과 같아야 합니다. Sim/rebake의29개 손상 조합에 대해 host validate/prepare 및 native 거부, lastgood·기존 immutable SHA 보존을 검사했습니다.

정상적인 신규/legacy 연속 재베이크의 원본 pose/key/steps 정의는 유지했습니다. lifecycle/connections/SDK root는 변경하지 않았습니다. 실제 Designer 실행은 여전히 부모 소유입니다.

## Designer embedded Python 긴 경로 수정

0bdcc481의 실제 앱 실행은 Sim 두 건 뒤 host Blobs.save의285자 파일 생성에서 중단됐습니다. 부모의 독립 probe에서 동일한285자 경로의 일반 write/read/stat는 실패하고 명시적인 Windows 확장 Unicode 경로는 성공했습니다. 자료는 output/evidence/embedded-path-probe/7c96e5cd84fb4e0d9262f5aa45dc4958/report.json에 있습니다.
fileio.py는 protocol에 쓰는 정상 논리 경로와 실제 I/O용 확장 경로를 분리합니다. core의 read/write/hash/stat/cache copy/원자 promotion과 provenance stat/read/save, 관련 이동 fixture의 깊은 파일 읽기·복사에만 적용합니다. 실제 resolve도 확장 경로로 수행한 뒤 정상 논리 경로로 돌아와 소유 범위를 검사합니다. 원본 JSON path bytes·해시·키는 고쳐쓰지 않으며 OS 설정·Designer 실행 파일·native/physics는 변경하지 않습니다.
회귀는 일반260자 초과 open/stat/mkdir/copy/replace를 실패시키는 guard를 사용합니다. root280자 이상의 한글 경로에서 실제 Sim→rebake→validation→promotion, 원자 promotion 실패 보존, raw blob SHA와 소유 경로 이탈 거부를 검사합니다. Desktop Python의 long-path-aware 설정에 의존해 통과시키지 않습니다. 실제 Designer 재검증은 부모가 수행합니다.

## Acceptance helper 실행 코드 신선도

bc26 실행은 기본 rebake·픽셀·rollback·취소/crash 뒤 이동 helper에서 실패했습니다. traceback의 줄과 prefix 없는 인자가 현재 소스와 달랐으며, 이전 실행에서 import된 helper 재사용으로 판단했습니다. 이 실패를 수정된 제품 fileio의 평가 결과로 취급하지 않습니다.
acceptance lane 안의 loader가 png_pixels/moved_fixture의 현재 raw 소스를 compile+exec하여 실행마다 고유 module을 만듭니다. 기존 base-name sys.modules와 pyc는 사용하지 않습니다. 각 소스 SHA를 실행 전 fingerprint와 대조하고 모든 helper 정의 함수의 CodeType이 같은 소스 compile 결과와 같음을 검사합니다. loader도 inline 현재 lane compile과 대조합니다. report의 helper_loader_freshness/helper_freshness에 source SHA·bytecode SHA·일치 판정을 기록합니다.
회귀는 두 base-name에 실패하는 stale module을 주입하고도 현재 decoder/이동 helper가 실행되는 것을 확인합니다. 기존 stale module이나 SDK root를 재생성·무차별 reload하지 않습니다. 이번 수정은 acceptance/회귀/문서에 한정하며 제품 core/native/worker는 그대로입니다.
