# 단계 2A 후보 인계

제품은 `D:\Git\SubstancePhysicsScatter` 안에서만 수정했습니다. Unreal 저장소와 외부 Git/remote는 변경하지 않았습니다.
승인된 단계 1 `8ebb02fe3beee81cd0110155661186b19025a676f50a0657417dc7df37b1442c`의 배포본·worker·manifest는 `accepted-stage1/`에 보존했습니다.

## 변경

- worker와 host가 schema v2 assets/pose를 사용합니다. 파일 SHA256과 자산 UUID는 별개이며 같은 파일을 여러 크기/가중치로 등록할 수 있습니다.
- 모든 자산 descriptor/크기를 확인한 뒤 정렬한 positive weight를 max로 정규화하고 Kahan 누적합니다. 선택/회전 RNG는 분리했습니다.
- host는 복사한 캐시를 다시 SHA 확인하고 worker는 읽은 실제 바이트를 Windows BCrypt로 확인한 뒤 그 바이트를 파싱합니다. 새 외부 dependency는 없습니다.
- 자산별 원본 메시를 보관하고 collider/render에 크기를 한 번만 적용합니다. 보수적인 초기 spacing과 변환 전 삼각형/작업 예산을 검사합니다.
- host/worker가 pose ID/자산/배열/유한성/단위 quaternion/크기를 확인합니다. 허용 오차 내 quaternion을 정규화하며 machine epsilon 수준에서는 동일 캐시의 반복 재베이크를 보존합니다.
- UI 표는 원본 파일 이름·가중치·자산 크기를 표시합니다. ID/hash는 기본 컬럼으로 노출하지 않습니다. 파일이 사라지면 모든 자산을 소유 캐시에서 복구합니다.
- v1 결과 표시와 단일 OBJ host 호출 호환 경로를 유지합니다. v1 재베이크는 새 작업 디렉터리/QProcess 전에 안내하고 차단합니다.
- connections/lifecycle/bridge의 기능 코드는 변경하지 않았습니다.

## 오프라인 검증

`scripts/verify_offline.py`는 UTF-8 로그를 `output/evidence/stage2-offline-tests.txt`와 `stage2-package.txt`에 씁니다.
전체 42개 unittest 중 41개 PASS, 실제 symlink 생성 1개는 Windows 권한 때문에 skip입니다. symlink 검사 분기의 mock 회귀는 PASS입니다.
Release worker 빌드, Python compileall, schema JSON 파싱, 0.2.0 배포본 생성 및 압축을 푼 worker의 두 자산 실제 실행을 확인했습니다.
선택기 10만 회/경계/재현/순서 반전, SHA known vectors·hashlib, 혼합 실제 베이크·0.25 크기/바닥 접촉, zero weight, 이동 캐시/원본 유실, 변조/pose/byte·triangle·work budget 거부 및 이전 결과 보존을 포함합니다.

## 실제 Designer 인계

이 후보의 실제 Designer 실행은 아직 하지 않았습니다. 부모가 독점 실행권을 유지합니다.
`tests/designer_smoke.py` → `designer_stage2.py` → 공유 수용 lane을 실행합니다. bridge 코드는 그대로이므로 새 F5 시작은 필요하지 않습니다. 기존 bridge가 만료됐다면 기존 시작 스크립트를 다시 실행해야 합니다.
새 UI는 수용 lane에서 별도 module로 로드해 파일과 bytecode를 확인합니다. 부모가 숨겨 보관한 기존 SDK root/registry는 이 lane에서 초기화하거나 새로 생성하지 않습니다.
수용 lane은 실제 UI 표/QProcess Sim 및 rebake, 두 자산 혼합·모든 decoded pixels, 독립 노드·외부 연결, rollback/cancel/crash, save/reopen, 이동 복사 캐시, 실제 archived v1 표시/재베이크 start=0을 검사합니다. 고유 WORK와 pre/post fingerprint를 기록합니다.
사용자 preview를 다시 보일 때는 부모가 최신 core/designer/ui를 reload한 뒤 검증된 lifecycle을 통해 같은 root에 새 child를 생성해야 합니다. 새로운 SDK root를 만들 이유는 없습니다.

## 남은 제한

2A의 실제 Designer 수용과 독립 검수 전에는 완료로 주장하지 않습니다. 예산은 전체 RSS 상한이 아닙니다. FBX/compound/Ground/Mask/PBR/periodic/실시간 3D·8K/SBSAR는 이번 후보에 포함되지 않습니다.

## 이동 fixture 보정

첫 2A live는 UI Sim 2회·재베이크·모든 픽셀·외부 연결·실패 rollback·취소/crash·저장/재열기를 통과한 뒤, 소유 결과 폴더 rename의 WinError 5로 중단됐습니다. 잠금 원인은 확정하지 않았습니다. 해당 실행의 core 증거는 그대로 보존합니다.
보정은 테스트 파일만 변경합니다. 로드한 main proof의 SBS/결과/원본 메시를 새 staging에 복사하고, XML 속성 안의 escaped JSON과 cache JSON을 구조적으로 staging 원본 경로로 변경합니다. 실제 저장된 상대 Linked filepath는 그대로 보존합니다.
oldmain fallback 0건·목적지 경로 사전 주입 0건·owned 경로 존재와 상대 Linked 불변을 검사한 뒤, byte-identical moved 복사본을 만듭니다. 한 번도 앱에서 열지 않은 staging만 park하고 source 경로 부재·moved 상대 Linked 파일 존재·main proof SHA 불변을 기록합니다. 모든 rename 대상은 resolve 후 고유 WORK 내부인지 검사합니다.
부모는 main의 자체 테스트 package만 unload하고 moved를 load한 뒤 실제 package path와 모든 bitmap getFilePath를 확인합니다. 어떤 update/relink도 하기 전에 moved graph export가 기존 decoded pixels와 일치해야 합니다. 다음으로 실제 UI에서 모든 캐시와 원본 파일 이름 복구를 검사하고 정상 UI 재베이크를 수행합니다. pre-relink display가 실패하면 그 상태로 보고합니다.
이 검증은 제품의 실제 상대 Linked 저장본 이동만 다룹니다. 임의의 절대 Linked 경로 자동 복구를 검증했다는 의미는 아닙니다. SDK 강제 release·전역 GC·native dock 호출은 추가하지 않았습니다.

## 최종 수락 후속 상태

2A 후보 `a39e7a27ba134da22b3d43fec53f7d804c03c219ce03a4167675ba79e3ab5a5d`는 최종 수락됐습니다. 실제 Designer report는 `output/designer_stage2/6e56d1e0b2f84d14bc80268dd0109148/report.json`, 독립 PASS는 `output/evidence/final-stage2A-independent-review-a39e7a27.json`입니다. 독립 decoded pixel 49개 비교와 live 전후 모든 manifest 파일 일치를 확인했습니다. 앞의 미실행·검수 전 표현은 당시 후보 상태를 기록한 이력입니다. 승인 배포본·소스·실제 fixture는 accepted-stage2A에 보존했습니다.
