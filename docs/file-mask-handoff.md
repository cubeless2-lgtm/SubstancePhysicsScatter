# File Scatter Mask 0.3.0 수락 인계

완결 계약은 [File Mask 계약](file-mask-contract.md)입니다. 승인 0.2.1의 기능·패널 수명·연결 처리는 유지하며 파일 PNG8/16 Mask만 추가했습니다. 승인 후보 `59327fe483e308a97f01035fdcbed4054a31f3a9c45fef465607eadcbdca3e8c`는 실제 Designer 수락과 최종 독립 검수를 모두 통과했습니다.

[최종 독립 검수](../output/evidence/final-file-mask-independent-review-59327fe4.json)는 PNG 469개 독립 디코딩, 픽셀 비교 244개, 빈 맵 30개 전체 픽셀 검사와 입력 159개 불변을 확인했습니다. 실제 앱의 원시 보고서는 [Designer report](../output/designer_file_mask/bcd59fb13492439cac367ece3d9f547b/report.json)에 있습니다.

승인 배포본·소스 ZIP·실제 fixture·검수 증거는 `accepted-stage2B-file-mask/`에 원본을 이동하거나 변경하지 않고 복사했습니다. [보관 증거](../accepted-stage2B-file-mask/archive-evidence.json)의 SHA256은 `fe04efd6c348f131d4a22f72f7a069733bd5ac56859d1d56c4e1a7ac7c488807`입니다. 이번 갱신은 문서 세 파일만의 후속 상태 정리입니다. 구현 입력이 동일하므로 59327fe4 검증 증거를 재사용하며 기존 manifest·배포본·보관본은 다시 쓰거나 재포장하지 않습니다.

## 구현 경계

- 신규 Sim은 schema2 / input2 / physics2 / bake2 / pose1입니다. Mask null도 input2입니다. 재베이크에서 format1과 legacy0.2의 원본 입력·pose·key·origin 파일을 rewrite하지 않습니다.
- full requested N의 asset 선택과 회전을 먼저 확정합니다. Mask는 별도 RNG로 후보 grid 중심을 거절하며 accepted k는 원래 선택의 prefix를 사용합니다. nonempty Jolt/BVH 계산과 asset/rotation RNG 표현식은 그대로 유지합니다.
- 검증된 빈 결과만 world/body/BVH를 건너뜁니다. 모든 OBJ 읽기·SHA·parse·기하/weight/scale·full requested budget·Mesh-too-large 검사는 all-black에서도 선행합니다.
- format2 최초 origin에 spawn metadata, initial_positions, 최초 execution을 저장합니다. 재베이크는 origin의 값과 배열 순서를 그대로 전달합니다. format1에 이 필드를 보충하지 않습니다.
- Mask snapshot은 소유 `inputs/<sha256>.png`에 복사한 후 다시 SHA를 확인합니다. 프로토콜의 논리 경로와 Windows 확장 Unicode I/O 경로를 분리합니다.

## Decoder와 의존성

zlib 1.3.2 공식 tar.gz의 실제 SHA256은 `bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16`입니다. CMake에 C 언어와 ZLIB::ZLIBSTATIC을 추가했고 shared/testing/install은 끕니다. Release는 정적 CRT /MT이며 zlib 라이선스와 pin metadata를 배포본에 넣습니다. 기존 고정 LodePNG 소스와 출력 encoder 호출은 바꾸지 않습니다.

Mask local LodePNG state에만 custom_zlib를 지정합니다. 모든 chunk의 순서·길이·CRC를 검사한 뒤 ancillary를 제거합니다. callback은 null/0 입력만 소유하며 정확한 expected bytes를 할당해 단일 Z_FINISH를 호출합니다. STREAM_END, 정확한 total_out, 남은 입력 0의 세 조건이 모두 필요합니다. 초기화 성공 경로에서는 inflateEnd를 호출하고 자체 메모리만 해제합니다. raw 출력도 RAII로 보호합니다. host는 exact expected max_length로 한 번 decompress하며 eof와 잔여 입력을 검사합니다. max_length=0 또는 무제한 flush는 사용하지 않습니다.

원본 PNG·sanitized PNG·LodePNG IDAT 임시본·scanline·decoded raw·uint16 Mask·zlib allocator와 메시/계획/출력 버퍼의 동시 예산을 보수적으로 계산합니다. 실제 allocator는 추가 내부 할당을 512MiB 작업 예산 안에서 확인합니다. 이 예산은 전체 프로세스 RSS 상한이 아닙니다.

## 수락 항목과 증거 위치

| 계약 항목 | 오프라인 검사 | 실제 Designer 검사·재사용 증거(PASS) |
| --- | --- | --- |
| none/white, RNG 독립, 원래 계산 | test_file_mask: omitted_white, actual_021_worker | none/white 실제 UI Sim·모든 채널 비교 |
| PNG8/16·축·nearest | test_mask_decoder: raw_values_orientation, test_file_mask: partial_prefix | partial8/16 pose·모든 픽셀, 비대칭 axes 초기 위치 |
| 정수 확률·p0/max 소비·종료 우선순위 | exact_probability_boundary, height_last_attempt | partial 상태·생성/요청 수·UI 사유 |
| all-black 정상 빈 결과 | black_empty_origin_pixels_two_rebakes, schema | all-black Sim→save/reopen→2회 rebake·모든 픽셀/metadata/origin |
| 부분 생성·prefix·요청 예산 | partial_prefix, allblack_does_not_bypass_assets | partial UI 결과·기존 외부 연결 회귀 |
| legacy/format1 보존 | test_compat 전체, actual021 fixture, format1_empty_rejected | 기존 0.2.0/v1 lane + 실제 승인 0.2.1 format1 재베이크 |
| Mask 변경·캐시 이동·누락/손상 | cache_change, mask_move_immutable, native_byte_tamper | none/white 전환 거부·staging 이동·캐시 복구·손상/누락 거부 |
| 압축/CRC/순서/자원/할당 실패 | test_mask_decoder 전체, host/native 교차 | 오프라인 증거 재사용 |
| 모순 spawn/origin/pose·bool·empty 픽셀 | host corruption, native_spawn_provenance, schema | host/native 오프라인 증거 재사용 |
| 설정 고정·선택 취소·오류 last-good | test_host_fileio, test_bridge, 기존 rollback 회귀 | 모든 UI 입력 잠금·picker 취소·invalid·missing·cancel/crash·metadata/current/decoded 픽셀 |
| 연결·독립 노드·저장/재열기·이동 | test_stage2/test_worker/test_moved_fixture | 기존 fixed acceptance 전체를 선행 실행 |
| helper 최신 소스·입력 identity | test_helper_freshness, manifest | inline compile+exec 고유 module, function CodeType 비교, pre/post fingerprint |

새 로그는 `output/evidence/file-mask-offline-tests.txt`, `file-mask-package.txt`, `file-mask-release-build.txt`, `file-mask-dependency-check.json`입니다. 개발 중 전체 테스트와 빌드를 겹친 첫 실험의 WinError32 결과는 `file-mask-development-tests.txt`에 남겨 두며 최종 수락 증거로 사용하지 않습니다. 이후 빌드·worker 테스트는 순서대로 실행합니다.

최종 `python scripts/verify_offline.py`는 Release 빌드, Python compile, schema 문법 및 실제 request/result schema 검사, 전체 77개 테스트(76 PASS·실제 symlink 권한 제약 1 skip, 127.870초), 패키징, 추출 배포본의 일반/empty 실행, dependency·보호 코드 확인까지 exit 0으로 통과했습니다. symlink 검증 분기의 mock 회귀는 별도로 PASS했습니다. actual0.2.1 worker와 nonempty pose·초기 위치·steps·settling·모든 decoded 맵이 일치했습니다.

## 실제 앱 실행 인계

고정 entry는 `tests/designer_smoke.py → designer_file_mask.py → designer_acceptance.py`이며, 마지막에 fresh `designer_file_mask_lane.py`를 실행합니다. bridge 요청은 기존 allowlist의 smoke만 사용하고 요청으로 코드·경로를 받지 않습니다. 새 SDK root나 dock을 만들지 않고 isolated test child만 생성합니다. 현재 사용자 panel은 재생성하지 않습니다.

새 package는 baseline에 없는 UID와 미저장 상태를 확인한 뒤 사용합니다. save/reopen/moved/archive 반환값은 고유 WORK 하위의 기대 SBS와 실제 getFilePath가 일치해야만 소유 대상으로 채택합니다. UID만으로 기존 사용자 package를 식별하지 않습니다.

실제 수락은 root가 bridge를 시작한 뒤 고정 smoke를 제출해 수행했습니다. 향후 bridge가 만료되면 `scripts/start_designer_bridge.py`를 다시 실행합니다. smoke 자체가 errors/fileio/maskio/compat/core/connections/designer를 다시 읽고 테스트용 최신 UI class를 별도 모듈로 생성합니다. lifecycle/__init__/connections/bridge 동작은 변경하지 않았습니다. preview/SDK root의 복원·관리는 root가 수행합니다.

## 남은 범위

0.3.0 File Mask 범위는 실제 Designer 수락과 최종 독립 검수를 마쳤으며 전체 제품의 완료를 의미하지 않습니다. Graph Mask, Ground, FBX, 분해, PBR, periodic, 실시간 3D, 8K 실증, SBSAR 및 clean-install 검증은 이번 범위에 포함하지 않습니다. Mask는 초기 중심의 확률만 제어하므로 물리 이동 뒤의 최종 영역 제한이나 정확한 생성 개수를 보장하지 않습니다.
