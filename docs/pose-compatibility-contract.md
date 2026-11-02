# 2A.1 pose 호환성과 provenance

0.2.1은 물리·베이크 계산을 바꾸지 않고 pose 전달 계약을 분리합니다. schema 2를 유지하며 pose/physics/bake/physics-input format의 현재 버전은 각각 1입니다. worker_version은 현재 실행과 일치합니다.

physics_inputs.json은 ID순 assets(id/hash/format/weight/scale)와 기본값을 채운 simulation(count40,width4,depth4,seconds12,seed1,edges walls,friction0.6,restitution0.05)을 담습니다. 경로·표시 이름·worker·bake는 제외합니다. host가 exact UTF-8 bytes와 SHA를 만들고 worker는 그 bytes를 읽어 SHA 및 request와의 semantic exact 일치를 검증합니다. 숫자 bool/비유한 값, unknown simulation/global scale, 범위 위반은 거부하며 weight -0은 +0입니다.

새 key의 bytes는 `physics_input_v1\n<physics_input_hash>\n<최초 physics contract 양의 십진수>\n`이며 SHA256을 사용합니다. 재베이크는 최초 key/계약을 유지합니다. legacy_0_2_0는 기존 key를 유지합니다.

pose envelope는 RH_Z_UP/meters/final_uniform_scale_on_original_vertices, format 버전, physics hash/key/scheme, 정확한 원본 pose와 최초 origin을 포함합니다. 검증은 원본 배열을 변경하지 않고 허용 quaternion 정규화는 깊은 계산용 복사본에만 적용합니다.

새 Sim은 origin_result.json을 먼저 close하고 raw SHA를 계산합니다. 이 immutable record는 최초 job/worker/physics contract/key/physics input identity/좌표·단위·scale/원본 poses/steps/settling만 담고 자기 SHA와 최종 result SHA는 넣지 않습니다. 최종 result는 origin 경로·SHA를 참조합니다. 현재 실행 worker/bake contract/operation/execution을 별도로 기록하며 rebake execution은 physics_executed=false,body_count=0,steps=0입니다. pose_origin은 최초 record를 유지하고 rebake_source는 직전 result의 job/worker/raw SHA입니다.

legacy는 schema2+worker0.2.0이며 신형 필드가 전혀 없는 경우만 허용합니다. 각 run의 원본 request/result를 확인하고 최대64개/visited job으로 bake chain을 최초 Sim까지 추적합니다. 절대 poses_path는 형식과 run ID를 확인한 뒤 현재 owned runs 아래에서만 읽습니다. 각 단계 job/key/assets/settings/poses/좌표·단위가 같아야 합니다. 원래 Python key-material exact bytes를 보존하고 old key/raw SHA와 semantic을 worker에서도 검증합니다. 누락·부분 신형·unknown 버전·손상·이탈·순환은 재Sim 안내로 거부하고 표시 이미지는 유지합니다.

provenance는 파일당16MiB, 고유 읽기/보존 합128MiB입니다. request/result/key-material/physics-input/origin 중 필요한 raw 파일만 SHA 주소로 dedup합니다. role/identity는 별도로 검증합니다. 이전 provenance 디렉터리 전체를 복사하지 않습니다. 원본 immutable 파일은 rewrite하지 않으며 실행 경로는 owned root+검증된 run ID/content hash로만 해석합니다.

steps와 body_count는 bool·분수를 제외한 비음수 정수입니다. 신규 Sim은 result.steps/execution.steps/source_steps/origin.steps가 같고 execution.body_count는 pose 수와 같습니다. rebake의 execution.steps/body_count만0이며 result.steps=source_steps=origin.steps를 유지합니다. legacy0.2의 bake.steps도 최초 물리 steps이며0으로 바꾸지 않습니다. 모든 legacy chain의 steps/settling과 현재 result·즉시 소비 bundle·최초 origin의 settling을 대조합니다. 모든 허용 float의0은+0.0으로 정규화하지만 이미 보관한 physical input/key-material raw bytes와 그 key는 바꾸지 않습니다.

파일명은 신규 실행의 request.json·physics_inputs.json·result.json·origin_result.json, 재베이크의 pose_source.json 및 provenance/<rawSHA>.json입니다. origin record는 close 뒤 실제 파일을 다시 읽어 SHA/내용을 확인합니다. rebake_source의 즉시 source tuple은 직전 요청이 소비한 pose_source raw SHA와도 대조합니다. 최초 physics_inputs raw bytes는 의미가 같으면 재직렬화하지 않고 재사용하므로 지원 format의 JSON 공백 차이가 origin key를 바꾸지 않습니다. 동일 physics input은 현재 physics_inputs.json을 재사용하고 provenance에 중복 보관하지 않습니다.

이동 fixture는 SBS metadata와 current.json의 실행용 포인터만 rebase합니다. 원본 request/result/physics_inputs/origin/pose_source 및 SHA blob은 바꾸지 않고 전후 SHA로 확인합니다. native provenance I/O는 긴 Windows 경로에서도 확장 경로를 사용합니다. 단계 2A의 실제 상대 Linked 이동 동작 범위는 유지합니다.

승인된 실제 0.2 fixture 31개 파일 354102bytes는 accepted-stage2A/fixtures에 읽기 복사했으며 원본/복사 SHA를 확인했습니다. 회귀는 고유 작업 복사본만 사용합니다. v1 표시 및 재베이크 worker start0은 유지합니다. 실제 Designer 수용은 부모가 실행하며 CLI 통과만으로 완료를 주장하지 않습니다.
