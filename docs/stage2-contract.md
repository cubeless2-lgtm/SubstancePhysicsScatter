# 단계 2A: 다중 OBJ와 가중치

승인된 0.1.0 worker·sdplugin·ZIP과 8ebb manifest는 `accepted-stage1/`에 보존합니다.
이번 범위는 다중 OBJ, stable asset UUID, 확률 가중치, asset별 크기, schema v2와 호환성 검증입니다.
connections/lifecycle를 재설계하지 않으며 Ground/Mask/FBX/compound/PBR/periodic는 추가하지 않습니다.

- asset_id는 소문자 UUID32hex이며 content SHA256과 별개입니다. 같은 파일을 여러 행에 등록할 수 있습니다.
- 모든 자산의 format/weight/scale/hash를 검증한 후 positive weight를 UUID ASCII 순으로 정렬합니다.
- max weight 정규화·Kahan 누적·mt19937 raw32/2^32 선택을 사용합니다. 양수 underflow와 누적 손실은 거부합니다.
- 선택 RNG와 회전 RNG는 분리합니다. 확률 가중치는 정확한 개수 보장이 아닙니다.
- global scale은 제거합니다. v1 단일 OBJ 호출의 simulation.scale만 단일 asset scale로 이전합니다. pose.scale은 collider와 render에 각 한 번만 적용합니다.
- host 복사 SHA 확인, worker 실제 바이트 SHA 확인 후 같은 바이트를 파싱합니다. 파일당 256MiB·aggregate 512MiB, parsed storage·2m transformed tris 및 tris*256+output buffers 512MiB 작업 예산을 검사합니다. 전체 RSS 제한을 보장하는 수치는 아닙니다.
- pose의 UUID/ID 중복·유한성·배열 길이·scale·단위 quaternion을 검증하고 허용 오차 1e-3 안에서 정규화합니다.
- v1 결과는 표시하며 v1 재베이크는 작업 폴더 생성·프로세스 시작 전에 한국어 안내로 차단합니다. 새 Sim 성공 전까지 current를 유지합니다.
- simulation key에는 정렬 ID/hash/weight/scale/settings/worker version을 포함합니다. 모든 asset cache는 프로젝트 이동 후 재해석합니다.

수용 기준은 상자+피라미드의 실제 혼합 베이크, scale 0.25, weight 0, 고정 seed/행 재정렬, SHA known vectors·hashlib 교차검사, 입력·pose·예산 오류, v1 start=0, 캐시 이동·원본 유실, 실패·취소·crash 보존입니다.
Designer 수용 테스트는 두 유형의 Sim/rebake·외부 연결·decoded pixel·save/reopen·moved cache를 검증합니다. 실제 앱은 부모가 실행합니다.
