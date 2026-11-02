# File Scatter Mask 승인 설계 계약

## 상태·소유권·범위

이 문서는 원안과 독립검수 보완을 합친 설계 PASS 계약이다. 설계 PASS는 File Mask 구현·빌드·실제 Designer 검수 PASS를 의미하지 않는다. 2A.1은 실제 앱 및 최종 독립 검수 PASS를 받았다. **Root의 2A.1 승인 보관본 복사가 끝나고 builder에게 명시적으로 인계된 뒤에만 Mask 구현에 착수한다.**

구현은 지정된 단일 writer가 담당한다. 다른 작업자가 동시에 작업하고 있으므로 그 변경을 수정하거나 되돌리지 않는다. 이 문서 작성 권한은 이 파일 하나에 한정되며 제품 변경 승인이 아니다. 실제 Designer 실행은 root가 소유한다.

이번 범위는 파일 기반 grayscale PNG Mask 선택, 소유 캐시, 확률적 초기 배치, 부분·빈 결과, UI 상태, 저장 pose 재베이크 호환성이다. Graph Mask, 그래프 snapshot, Ground Height, PBR, periodic, 8K 지원 확대는 후속이다. 신규 dependency는 아래 bounded decoder용 고정 zlib 1.3.2 하나로 제한한다. 기존 origin/provenance 파일 생성 순서·SHA·체인 검증·불변 보존 계약을 변경하지 않는다.

Mask는 초기 객체 중심의 생성 확률이다. 물리 시뮬레이션 후 객체가 Mask 밖으로 이동하는 것은 허용된다.

## 버전과 입력 identity

신규 시뮬레이션은 physics_input_format_version=2, physics_contract_version=2를 사용한다. pose_format_version=1은 유지한다. bake_contract_version=2는 빈 장면 출력 규약을 추가하며 기존 nonempty 베이크 계산은 변경하지 않는다. schema_version=2는 유지한다.

물리 입력 format 2는 기존 asset_id 정렬 assets와 정규화 simulation에 scatter_mask 필드를 추가한다. 비활성 값은 null이다. 활성 값은 content_hash, format="png", interpretation="raw_linear_probability", sampling="nearest", placement="grid_rejection_v1"만 갖는다. 경로·파일명·UI 상태는 identity에서 제외한다. 알 수 없는 필드는 거부한다.

새 simulation_key는 승인된 key_scheme 생성 규칙과 최초 physics contract 2를 사용한다. 재베이크에서 최초 키·origin을 보존하며 현재 계약으로 재계산하지 않는다. canonical 입력 파일의 정확한 바이트 SHA를 사용하고 C++에서 JSON을 다시 직렬화해 Python hash를 재현하지 않는다. semantic 비교와 실제 자산 바이트 검증도 유지한다.

weight 등 정규화 identity의 -0.0은 +0.0으로 변환한다. immutable 원본 provenance 바이트는 변경하지 않는다. 모든 수치는 finite여야 한다. seed는 uint32 정수이며 bool·소수는 거부한다. count 최대 5000 등 기존 범위는 완화하지 않는다.

## 이전 결과와 재베이크

- 승인된 0.2.1 input format 1 / physics contract 1 pose는 계속 재베이크할 수 있다.
- format 1은 Mask가 없는 입력으로만 해석한다. 원본을 format 2로 다시 쓰거나 hash·simulation_key를 변경하지 않는다.
- 현재 UI에서 Mask가 비활성이고 assets와 simulation의 의미가 같으면 format 1 원본과 비교하여 허용한다.
- Mask 활성화는 all-white라도 입력 변경이며 재시뮬레이션이 필요하다.
- format 2 원본은 활성 여부·Mask hash·정책까지 일치해야 한다. 모르는 형식을 downgrade하지 않는다.
- 0.2.0 명시적 adapter와 0.1 표시 유지·재시뮬레이션 요구를 유지한다.
- 새 1000m 초기 높이 제한은 contract 2 신규 시뮬레이션에만 적용한다. format 1 bake-only pose에 소급하지 않는다.

생략과 all-white는 지원 범위에서 동일 seed·assets·simulation일 때 선택 자산·초기 pose·최종 pose가 같아야 한다. 하지만 실제 입력이 다르므로 physics identity는 다르다. pose 원본과 계산용 복사본의 분리, 최초 origin 보존은 기존 계약대로 유지한다.

## PNG 지원 및 bounded decode

초기 지원은 비인터레이스, alpha 없는 grayscale PNG 8/16-bit다. RGB, palette, alpha 포함, interlace는 명시적으로 거부한다. gamma/sRGB metadata를 적용하지 않고 저장 숫자를 raw linear 확률로 사용한다. 8-bit 값은 257을 곱하여 16-bit 정수 범위로 대응시킨다.

고정 한도:

- 입력 파일: 64 MiB 이하.
- 각 축: 8192 이하, 양수.
- 총 픽셀: 16,777,216 이하.
- 최종 uint16 grayscale 버퍼: 32 MiB 이하.
- 압축 IDAT 합계: 64 MiB 이하.
- inflate 결과: 정확히 H × (1 + W × bit_depth / 8) 바이트. 행당 filter byte를 포함하며 최대 33,562,624바이트.

모든 곱셈·덧셈에 overflow 검사를 적용한다. header를 검사한 후 기대 inflate 크기를 실제 decoder 출력 상한으로 적용한다. 초과 출력은 즉시 중단하고 부족한 출력도 거부한다. 최종 버퍼 크기 사후 검사만으로 bounded decode를 대체하지 않는다.

IHDR은 첫 chunk, 길이 13, 정확히 하나여야 한다. bit depth·color type·compression/filter method를 decode 전에 확인한다. 중복 또는 불일치 IHDR, 잘린 chunk, CRC 오류, 잘못된 행 filter, 비연속 IDAT, 누락 IEND, IEND 이후 추가 데이터는 거부한다. 알 수 없는 critical chunk도 거부한다.

text, 압축 text, ICC 등 불필요한 ancillary chunk는 길이·CRC만 검사하고 건너뛴다. 내용 해석이나 별도 inflate를 수행하지 않는다. 기존 decoder가 이 제한을 제공하지 않으면 bounded 경로를 구현해야 한다.

## 승인된 decoder 보완 설계

근거는 같은 evidence 디렉터리의 `file-mask-lodepng-bounds-research.md`와 `file-mask-zlib-candidate-research.md`다. 이 보완안은 독립 설계 검수 PASS를 받았다. 공개 API 사용의 타당성에 대한 판정이며 실제 hard cap, 정상 exact-size 처리, 빌드·메모리 안전성은 구현 후 수락 시험으로 증명해야 한다. 기존 File Mask 기능 계약과 2A.1 최종 수락 후 착수 조건은 유지한다.

의존성은 공식 zlib 1.3.2 tar.gz로 고정한다. URL은 https://www.zlib.net/zlib-1.3.2.tar.gz 이며 공식 기록 SHA-256은 `bb329a0a2cd0274d05519d61c667c062e06990d72e125ee2dfa8de64f0119d16`이다. 아직 이 작업에서 다운로드·아카이브 hash 검증·빌드를 수행하지 않았다. Writer가 취득 후 정확한 hash를 검증하고 버전·출처·zlib 라이선스를 배포 기록에 포함한다. 고정 버전의 공개 헤더 근거는 https://raw.githubusercontent.com/madler/zlib/v1.3.2/zlib.h 이다. 정적 링크와 기존 MSVC 런타임의 일치를 검증한다.

기존 고정 LodePNG 소스와 encoder는 변경하지 않는다. Mask용 로컬 decoder state에만 `custom_zlib` callback을 설정한다. `color_convert=0`, `read_text_chunks=0`, `remember_unknown_chunks=0`, CRC 및 critical 오류 무시 비활성 상태를 사용한다. 원본에 대한 strict preflight에서 unknown ancillary까지 모든 CRC·chunk 순서를 검사한다. grayscale tRNS·PLTE와 interlace를 거부하고 ancillary는 해석·inflate 없이 제거한다. decoder에는 검증된 IHDR/연속 IDAT/IEND만 포함한 정제 PNG를 전달한다.

callback의 현재 고정 호출 전제는 진입 시 `*out == nullptr`, `*outsize == 0`이다. 전제가 다르면 즉시 오류로 반환하며 기존 caller 메모리를 해제하거나 덮어쓰지 않는다. 정상 전제에서 정확한 expected 크기의 malloc 호환 버퍼를 할당한다. callback context의 expected는 검증된 IHDR 계산값이다.

zlib wrapper 전용 초기화를 사용하고 전체 IDAT 입력과 정확히 expected 크기의 출력 버퍼를 제공하여 `inflate(..., Z_FINISH)`를 한 번 호출한다. 성공은 반환값 `Z_STREAM_END`, `total_out == expected`, `avail_in == 0`을 모두 만족하는 경우뿐이다. 실패 시 버퍼를 늘리거나 추가 출력용 반복 호출로 우회하지 않는다. raw DEFLATE, gzip, preset dictionary, 연결된 복수 stream, 입력 trailing garbage를 거부한다. wrapper와 Adler 검증을 끄지 않는다.

정확한 출력 크기에 도달한 뒤 trailer만 남은 정상 입력을 성공적으로 처리하는지 시험한다. 출력 용량 소진 자체는 stream 종료의 증거가 아니다. 정상 trailer 처리, 추가 해제 출력, 입력 trailing garbage를 위 세 성공 조건으로 구분하고 각각 fixture를 둔다.

초기화 성공 후 모든 경로에서 `inflateEnd`를 호출한다. 실패 시 callback 소유 출력은 자체 free하고 null/0을 유지한다. 성공 시에만 malloc 영역을 LodePNG에 전달한다. 현재 LodePNG allocator가 해당 영역을 호환 방식으로 해제하는지 검증한다. C callback 경계를 C++ 예외가 넘어가지 않게 하고 실패 시 부분 결과를 전달하지 않는다. zlib 내부 할당 실패도 정상 오류로 처리한다.

512 MiB 동시 작업 예산에는 원본 입력, 정제 PNG, LodePNG의 IDAT 복사, inflate 출력, raw 출력, 최종 uint16 Mask, zlib 내부 할당 및 기존 mesh/bake 버퍼를 포함한다. 단순히 최종 Mask 크기만 합산하지 않는다. 내부 할당은 계측 또는 제한 allocator를 통해 예산 준수를 검증하며 산술 overflow를 검사한다.

추가 필수 fixture는 악성 stored block 65,535바이트, 경계를 넘는 Huffman back-reference, expected−1/exact/expected+1, exact 출력 뒤 정상 trailer, 잘린 trailer·Adler 오류, trailing garbage·연결 stream·dictionary/raw/gzip, 압축 ancillary가 있어도 그 데이터에 대한 inflate 미발생, unknown ancillary CRC 오류다. 초기화·출력 할당·zlib 내부 할당 실패 및 inflate 실패에서 누수·중복 free·부분 출력 전달이 없는지도 검증한다. 이 시험의 성공을 관측하기 전에는 실제 hard-cap 수락 완료라고 보고하지 않는다.

## 소유 캐시와 무결성

Host는 inputs/<sha256>.png에 임시 복사 → 실제 SHA 확인 → atomic rename 순서로 보존한다. Worker는 읽은 동일 바이트의 SHA를 확인한 후 그 바이트를 decode한다. 검사 후 경로를 다시 열어 다른 바이트를 decode하지 않는다.

원본 경로는 편의 정보다. 원본이 없어도 소유 snapshot으로 실행할 수 있다. 캐시 누락·손상 시 다른 파일로 조용히 대체하지 않는다. 이동·복사 시 현재 소유 root와 content hash로 실행 경로만 재해석하고 원본 provenance JSON은 수정하지 않는다.

## Grid 배치와 RNG

요청 수 N의 자산 선택·회전을 먼저 확정한다. Mask RNG는 자산 선택·회전 RNG와 분리한다. Mask 거부는 기존 RNG를 소비하지 않는다. 수락 객체 k는 요청 목록의 asset[k]와 rotation[k]를 사용한다. 부분 결과는 그 목록의 prefix다.

requested_max_radius는 요청된 선택 목록 전체의 원본 반경 × 최종 유효 scale의 최댓값이다. pitch=requested_max_radius×2.2, cols=max(1,floor(width/pitch)), rows=max(1,floor(depth/pitch))를 사용한다. 기존 후보 j의 cell/layer/XYZ 계산은 유지한다. 거부되어도 j는 증가한다.

Mask는 grid 중심에서 평가한다. 흰 픽셀이 있어도 grid 중심과 만나지 않으면 생성되지 않을 수 있다. 연속 좌표의 균일 sampling을 보장하지 않는다. OBJ 원점이 멀면 반경이 커진다. bounding sphere 간격을 사용하지만 실제 초기 겹침은 fixture로 검증하며 무조건 무겹침을 주장하지 않는다.

좌표 규약:

```text
u = x / width + 0.5
v = 0.5 - y / depth
column = min(W-1, floor(u*W))
row = min(H-1, floor(v*H))
```

영역 밖은 확률 0, 정확한 경계는 가장자리 픽셀이다. 이미지 위쪽은 +Y다. nearest만 지원하며 bilinear는 제공하지 않는다.

```text
mask_rng = mt19937(seed XOR 0x4D41534B)
r = 원시 uint32 출력
p = 0..65535 sampled integer
accept iff uint64(r)*65535 < uint64(p)*4294967296
```

활성 Mask의 일반 후보는 p=0 또는 65535여도 RNG를 정확히 한 번 소비한다. 전체 all-black 조기 종료만 예외다. 확률 0은 항상 거부하고 최대값은 항상 수락한다.

## 후보 순서와 종료

max_attempts=min(50000,N*10)이다. 전체 all-black은 실제 decode된 픽셀 검사로 확인하고 attempt=0, 생성=0으로 종료한다. 일반 경로 순서는 다음과 같다.

1. attempt_count < max_attempts 확인.
2. 후보 j 생성.
3. attempt_count를 1 증가.
4. 중간 계산·좌표 finite 검사. 실패는 작업 오류다.
5. initial_top=center_z+requested_max_radius 계산.
6. initial_top>1000m이면 initial_height_limit 종료.
7. sampling 및 활성 Mask RNG 한 번 소비.
8. 확률 비교 후 수락 또는 거부.
9. 수락 수 N이면 requested_count_reached 종료.

높이에 걸린 후보도 attempt에 포함하지만 sampling/RNG는 하지 않는다. 마지막 허용 후보가 높이에 걸리면 height가 attempts보다 우선한다. 마지막 후보가 N번째 수락이면 complete가 attempts보다 우선한다. 그 외 최대 후보 처리 후 N 미충족이면 attempts_exhausted다.

생략/all-white에도 같은 신규 높이 한도를 적용한다. 지원 범위에서는 최초 N개 grid 후보가 동일하므로 기존 정상 초기 배치를 보존한다. 초과 극단 설정의 지원 제한은 명시한다.

## 자원 예산과 zero geometry

요청 목록 전체로 기존 메시 입력·삼각형·작업 예산을 먼저 검사한다. all-black도 잘못된 asset이나 예산 초과를 우회하지 않는다. 실제 수락 목록 확정 후 실제 예산을 다시 검사한다. 모든 검사는 body 생성과 transformed triangle 복제 전에 끝낸다.

기존 200만 transformed triangle 및 512 MiB 작업 예산을 유지한다. 작업 예산에는 Mask decoded buffer와 동시에 살아 있는 inflate/필터/입력 버퍼 등 추가 작업 저장량을 포함한다. 불필요한 버퍼는 해제하며 예산을 전체 프로세스 메모리 보장이라고 표현하지 않는다.

생성 0이면 Jolt 초기화·body 생성·BVH 생성·빈 BVH 조회를 생략한다. PNG 생성과 정상 검증·승격은 수행한다. pose가 단순 누락된 malformed 결과를 empty로 보정하지 않는다.

All-black 조기 종료는 후보 sampling·물리 실행을 생략하는 최적화이지 입력 검증 면제가 아니다. 실제 OBJ 바이트 SHA와 parse·기하 유효성, asset ID·weight·최종 scale·simulation 범위, 요청 N개 자산 선택과 전체 예산, 요청 최대 유효 반경의 finite 검사와 기존 `radius*2 >= min(width,depth)`의 `Mesh too large for region` 거부 조건을 먼저 만족해야 한다. Mask의 무결성·bounded decode와 실제 all-black 확인도 필수다. 이 검사들을 통과한 뒤에만 attempts=0의 정상 empty를 반환한다. Jolt/BVH 생략은 world·body·렌더 가속 구조를 생성하지 않는다는 뜻이며 원본 메시 구문·기하·배치 가능성 검증까지 생략한다는 뜻이 아니다.

## 결과 metadata 진리표

필수 필드: requested_count, spawned_count, attempt_count, max_attempts, spawn_status, spawn_stop_reason.

```text
requested_count == normalized simulation.count
spawned_count == len(poses) == len(initial_positions)
0 <= spawned_count <= requested_count
0 <= attempt_count <= max_attempts
```

| 상태 / 사유 | 필수 조건 |
|---|---|
| complete / requested_count_reached | spawned=N, N<=attempt<=max |
| partial / attempts_exhausted | 0<spawned<N, attempt=max |
| empty / attempts_exhausted | spawned=0, attempt=max |
| partial / initial_height_limit | 0<spawned<N, 1<=attempt<=max |
| empty / initial_height_limit | spawned=0, 1<=attempt<=max |
| empty / all_black | spawned=0, attempt=0, 검증된 활성 Mask의 모든 픽셀=0 |

다른 조합은 거부한다. all-black 여부를 요청의 주장만으로 신뢰하지 않는다.

빈 최초 시뮬레이션은 origin·실행 기록 모두 physics steps/body count=0, settling=not_run, pose와 initial_positions는 빈 배열이다. 재베이크는 기존 origin을 보존하고 현재 실행의 physics steps/body count=0을 기록한다.

신규 Sim의 `execution.physics_executed`는 `spawned_count>0`과 같아야 한다. 빈 Sim은 false이고 nonempty Sim은 true다. execution의 physics body count는 동적 scatter body 수이며 바닥·벽의 static body를 포함하지 않는다. nonempty Sim에서는 이 수가 spawned_count와 같아야 한다. 재베이크의 현재 execution은 항상 physics_executed=false, physics body count=0, physics steps=0이다. 최초 origin의 execution·steps·settling은 현재 실행과 별도로 보존하고 검증한다.

Input format 2 / physics contract 2의 immutable `origin_result.json`에는 requested_count, spawned_count, attempt_count, max_attempts, spawn_status, spawn_stop_reason, initial_positions와 최초 execution을 필수로 기록한다. Host와 native는 다음 관계를 검증한다.

```text
origin.requested_count == origin의 검증된 물리 입력 simulation.count
origin.spawned_count == len(origin.poses) == len(origin.initial_positions)
origin.max_attempts == min(50000, origin.requested_count*10)
```

initial_positions의 각 항목은 bool을 제외한 유한한 숫자 정확히 3개로 구성한다. Spawn 진리표, 최초 execution, steps·settling의 일관성도 검사한다. 재베이크 result의 pose·spawn metadata·initial_positions는 검증된 origin에서 정확히 이어받으며 숫자 값과 배열 순서가 같아야 한다. 현재 요청이나 직전 result에서 다시 계산·보충하지 않는다. 원본 provenance 파일은 바이트 단위로 보존한다.

Format 1 origin에는 새 spawn metadata·initial_positions·최초 execution 필드를 요구하거나 추정해서 추가하지 않는다. 기존 format 1 계약으로 검증하며 필드 부재를 format 2 empty로 해석하지 않는다.

빈 맵은 유효한 height_min<height_max metadata를 유지한다. Height 전체 0은 height_min을 뜻한다. Normal 전체 (128,128,255), Coverage 전체 0, clipped samples=0이어야 한다. Worker는 결과 생성 전, host는 승격 전에 일관성을 검사한다. 빈 결과에도 기존 이미지 형식 검사와 atomic 정상 승격·실패 rollback을 적용한다.

## UI

Mask 활성화, 파일 선택, 사용 중인 snapshot 상태, 요청/생성 수, 종료 사유를 표시한다. partial/empty를 worker 실패로 표시하지 않는다. Mask가 초기 중심 확률이며 물리 이동은 영역을 벗어날 수 있음을 설명한다.

잘못된 경로·지원하지 않는 PNG·누락 캐시·재베이크 입력 변경은 명확히 알린다. 실행 중 설정 변경이 active request에 섞이지 않도록 설정을 고정하거나 컨트롤을 잠근다. 선택 취소가 기존 유효 Mask를 무심코 지우지 않게 한다.

## 필수 수락 검증

1. 생략/all-white의 선택 asset, 초기 위치·회전, 최종 pose 동일. input identity는 다름.
2. 대응 PNG8/PNG16 선택 결과 동일. 좌우·상하 비대칭 fixture로 축 방향·nearest 경계 검사.
3. 정수 확률 0·최대값·경계값, p0/max RNG 소비, asset/rotation RNG 독립 검사.
4. all-black attempt0·body0·steps0, 정상 빈 출력 전체 픽셀·범위 metadata, 승격·저장·재열기·재베이크 검사.
5. 희박 Mask의 attempts 종료, 높이 종료, 마지막 attempt에서 높이/완료 우선순위, prefix와 개수 일치 검사.
6. 기존 grid 간격·초기 겹침·높이 한도 검사. nonfinite 계산은 정상 partial이 아니라 오류로 처리.
7. 0.2.1 format1 무물리 재베이크와 nonempty 맵 동일성. 1000m 제한 소급 금지. 기존 0.2.0/v1 회귀.
8. Mask 활성 전환·내용 변경 시 재베이크 거부. bake 설정만 변경하면 원본 pose와 origin 유지.
9. 원본 삭제·프로젝트 이동 후 소유 캐시 복원. 캐시 누락·손상·same-byte SHA 불일치 거부.
10. 작은 IHDR/과대 IDAT inflate, 잘림, 중복·불일치 IHDR, CRC/filter 오류, interlace, 비연속 IDAT, IEND 오류, 압축 ancillary chunk, 크기·픽셀·예산 초과 negative fixture.
11. pose 누락, 길이 불일치, nonempty origin/empty 결과, 허위 all-black, 모순 reason·steps·settling을 거부하고 마지막 정상 결과 보존.
12. UI 잘못된 경로·형식·누락 snapshot·선택 취소·실행 중 변경·worker 실패/취소 negative test.
13. 기존 다중 asset, provenance·legacy chain, 복제/이동 및 사용자 후처리 연결 회귀.
14. 빈 Sim → 저장·재열기 → 재베이크에서 origin 파일·pose·spawn metadata·initial_positions 불변, 최초 및 현재 execution의 false/body0/steps0 일치.
15. Format 2 origin의 spawn metadata·initial_positions·execution 손상과 bool 좌표를 거부한다. Format 1에는 새 필드를 요구하거나 만들어 넣지 않는다.
16. All-black + oversized mesh, 잘못된 OBJ, 요청 전체 예산 초과 조합은 정상 empty가 아니라 오류여야 한다. 각 실패에서 last-good 이미지·설정·연결·current pointer를 보존한다.

단일 writer는 후보 파일 identity·테스트 로그·decoded 이미지 증거를 고정하여 독립 검수에 인계한다. 실제 Designer 검증은 root가 수행한다. 구현 완료와 독립 검수 PASS가 나오기 전에는 File Mask 기능 완료로 보고하지 않는다.
