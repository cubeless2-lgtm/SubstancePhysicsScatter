# 구현 계약 및 진행 기록

사용자 승인: 독립 `D:/Git/SubstancePhysicsScatter`, 필요한 C++/Python/라이브러리 허용. 원격 생성·push는 범위 밖입니다.
협업 절차: Ieta 기획 → independent design PASS → Tivret 단독 구현 → frozen candidate 독립 검토.

## 단계

1. OBJ/Jolt open·walls/precise triangle bake/Height Normal Coverage/Designer 연동.
2. 여러 메시와 가중치, FBX, convex decomposition, Ground Height·Scatter Mask.
3. UV 재질 PBR, Object ID와 Random, Designer 후보정 노출.
4. 주기 경계 접촉·베이크와 3×3 검증.
5. 실시간 3D 프리뷰, 비정사각형·8K, cache cleanup, SBSAR 및 배포 검증.

단계 1 core와 패널 수명은 실제 Designer 및 독립 검수 PASS(승인 후보 8ebb02fe), 단계 2A 다중 OBJ/가중치는 실제 앱·최종 검수 PASS(a39e7a27), 2A.1 원본 pose 호환성은 실제 앱·최종 검수 PASS(63eeb99a)입니다. 각 accepted-stage 보관본은 수정하지 않습니다. 실제 0.2.1 증거에는 독립 PNG 디코딩 214개와 픽셀 비교 97개가 포함됩니다.

0.3.0 File Scatter Mask는 파일 기반 PNG8/16 범위로 실제 Designer 수락 및 최종 독립 검수 PASS(59327fe4)를 받았습니다. PNG 469개 독립 디코딩·픽셀 비교 244개·빈 맵 30개 전체 픽셀 검사와 입력 159개 불변을 확인했고, 승인본은 `accepted-stage2B-file-mask/`에 복사해 보관했습니다. [최종 검수 증거](../output/evidence/final-file-mask-independent-review-59327fe4.json)를 보존합니다. Graph Mask, Ground, FBX, 분해, PBR 및 periodic는 이 단계에 포함하지 않습니다.

## Periodic 조기 실험 결론(당시 기록)

현재 Jolt 기본 공개 사용 경로에 XY periodic boundary 옵션을 연결하지 않았습니다.
ContactListener는 접촉 통지 경로이며 임의의 경계 접촉 제약을 자동 삽입하지 않습니다.
Kinematic ghost만 추가하면 원본 양쪽의 반작용을 보장할 수 없으므로 정식 기능에 넣지 않습니다.
현재 worker는 `edges=tileable` 요청을 거부하는 음성 검증만 통과했습니다. 이것은 periodic 물리의 실현 가능성을 검증한 것이 아닙니다.

향후 실험은 무중력·무마찰 동일 질량 두 구를 일반 접촉 기준선과 경계 접촉으로 비교합니다.
CollisionDispatch 임의 transform 질의와 custom constraint 가능성을 살피되, 접촉 impulse·마찰·warmstart·position correction을 모두 검증합니다.
기준은 양쪽 속도·운동량, 자기/중복 접촉 부재, corner, 장시간 에너지 증가 여부입니다.
확장 영역 중앙 자르기를 채택하면 반드시 근사 방식으로 표시합니다.

## 데이터 계약

- 내부 RH Z-up, 미터. OBJ는 자체 unit metadata가 없으므로 Z-up/meter를 명시적으로 요구합니다.
- 입력/출력 JSON schema_version=2, 매 실행 고유 job_id. stdout JSONL, stderr 로그.
- 신규 Sim의 pose format=1, physics input/physics/bake contract=2입니다. Mask 없음도 format2의 null로 명시합니다. 승인된 format1 pose는 원본 입력 bytes/hash/key를 유지한 채 재베이크합니다. schema1 이미지는 표시하되 pose 재베이크는 작업 시작 전에 거부합니다.
- 물리 identity는 정렬된 asset ID/content hash/weight/scale, 정규화 simulation, format2 Mask snapshot hash/policy를 포함하며 경로·표시명·worker 버전을 제외합니다. exact physics_inputs.json raw bytes를 해시하고 `physics_input_v1\n<hash>\n<최초 physics contract>\n`의 SHA256을 키로 사용합니다. legacy0.2는 원래 키를 보존합니다.
- 재베이크는 이전 pose identity와 immutable 최초 origin·직전 source를 검증할 때만 허용합니다. 현재 execution은 항상 무물리 body0/steps0이며 호환용 result.steps와 source_steps는 원래 physics steps를 유지합니다.
- 요청마다 새 폴더 사용. PNG CRC·payload·형식·해상도, 결과 ID를 확인 후 current.json atomic replace.
- Designer 출력은 stable output node를 유지하고 내부 bitmap node만 교체. 실패 시 기존 선 복원.

## 아직 닫지 않은 설계 항목

승인 2A/2A.1에서 상대 Linked 파일의 패키지 이동, 소유 asset cache 복구, cancel/crash·compute/store/promotion 실패의 마지막 정상 결과 보존을 실제 앱에서 확인했습니다. 0.3.0에서는 File Mask의 정상 빈 결과·저장/재열기·재베이크·캐시 이동과 기존 호환성 회귀도 실제 앱에서 수락됐습니다. 임의 절대 Linked 파일 자동 복구는 주장하지 않습니다. 일반 duplicate의 독립 그래프화, Undo/Redo transaction, cache quota, 일반 Graph 구조 확장, ground input export, SBSAR 16-bit precision, clean-install proof는 후속이며 전체 제품은 아직 완료되지 않았습니다.

## 2026-11-01 현재 통합 상태

위 accepted-stage와 초기 periodic 항목은 당시 기록이다. 현재 별도 로컬 검수 UI의 OBJ/FBX·PBR·주기 경계 검증은 `../local_review/README.md`에 정리했다.

Designer Graph Mask는 검증된 Noise/Invert terminal 범위에서 통합을 마쳤다. CPU 평가 범위 수정 후 raw·PNG exact0을 확인했고, 최종 `../output/designer_bridge/graph-mask-final/750f56d1542545d59d2400185161598e/report.json`에서 실제 선택→Inspect→Sim64→Saved128→대상 SBS 저장·재열기→원본 소스 부재 Saved64→소스 복원·fresh Inspect→queued 취소·metadata rollback을 검증했다. native3회 중 Saved2회는 physics0이고 pose/origin을 보존하며64 출력3채널은 최초 결과와 byte-exact다. 사용자 패널·저장파일·CPU 설정을 보존하고, 이전92c 폴더 hold 실패는 원문으로 남겼다. 허용 오차0·컴퓨터 유즈0이며 독립 최종 검수에서 이 지원 경로의 통합을 수락했다.

일반 Designer Graph 전체 지원, ground input, SBSAR 배포 재현과 clean-install 등은 별도 후속이다. 제한된 Graph Mask 통합 완료를 이 범위 전체의 완료로 확대하지 않는다.
