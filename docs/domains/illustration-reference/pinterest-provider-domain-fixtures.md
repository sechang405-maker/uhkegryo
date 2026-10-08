# Pinterest Provider 도메인 검수 Fixture — 10건

> 이 문서는 기존 활성 TERM_CARD를 근거로 만든 **OSC 도메인 검수 기준**이다. 실제 Pinterest 검색 결과나 외부 이미지의 품질을 주장하지 않는다. 원본 TERM_CARD는 수정하지 않으며, 구현 시 fake provider fixture와 사람 검수 기준으로만 사용한다.

- 검수 상태: ✅ OSC 도메인 검수 완료 · fixture 기준 확정
- 검수자: 오세창 (OSC)
- 검수일: 2026-09-28
- Provider 계약 대조: PR40 병합 커밋 `071616f` 기준으로 `PinterestProvider.search()`와 `RoleSearchOutcome` 계약을 재확인했다.

## 선정 기준

- 활성 조건 `runtime_eligible=true && mvp_status=active_in_current_contract`를 통과한 카드만 참조했다.
- 카드 수 비율 대신, 체형·포즈·시점·투시·레이아웃을 각각 2개씩 골라 Provider 검수 범위를 고르게 했다.
- 검색어는 각 카드의 `query_fragments`만 사용한다. 구현 시 결정론 URL builder가 끝에 `drawing`을 한 번 덧붙이는 규칙은 유지한다.
- 아래 `제외` 조건은 카드의 `confidence_gate.do_not_infer_from`를 그대로 옮긴 것이다.

| 역할 | 건수 | 선택 카드 |
| --- | ---: | --- |
| 체형 (`body`) | 2 | `body_hourglass`, `body_inverted_triangle` |
| 포즈 (`pose`) | 2 | `pose_contrapposto`, `pose_sitting` |
| 시점 (`view`) | 2 | `view_front`, `view_three_quarter` |
| 투시 (`perspective`) | 2 | `perspective_three_point`, `perspective_foreshortening` |
| 레이아웃 (`layout`) | 2 | `composition_rule_of_thirds`, `layout_composition` |

## Provider 상태 적용 범위

각 도메인 fixture는 정상·검색 0건·검색 실패의 세 결과를 모두 적용 대상으로 삼는다. Pydantic 필드값, reason code, thumbnail 조립 방식의 단일 기준은 [API 계약](../../specs/api-contract.md)과 [Pinterest Provider 설계](../../specs/pinterest-widget-crawler.md)다. 이 문서는 그 기술 계약을 다시 정의하지 않으며, 카드별 검색어와 도메인 적합성만 검수한다.

## Fixture

### DPF-01 · 모래시계형

- 사용자 입력: `어깨와 골반 폭은 비슷하고 허리는 들어간 캐릭터 체형 자료가 필요해.`
- 기대 선택: `body_hourglass` (`body`)
- 카드 검색 조각: `hourglass body` + `proportion reference`
- 확인: 어깨·골반의 전체 폭이 비슷하고, 몸통에서 허리선이 들어가는지 본다.
- 제외: 의상 허리선만 조여 보이거나 코르셋·큰 치마 때문에 그렇게 보이는 이미지만으로 선택하지 않는다.

### DPF-02 · 역삼각형

- 사용자 입력: `어깨가 넓고 골반은 상대적으로 좁은 캐릭터 체형을 보고 싶어.`
- 기대 선택: `body_inverted_triangle` (`body`)
- 카드 검색 조각: `inverted triangle body` + `proportion reference`
- 확인: 어깨 또는 상체 폭이 골반보다 넓고, 위에서 아래로 갈수록 좁아지는 외곽선인지 본다.
- 제외: 패드·망토·퍼프소매처럼 의상만 넓어 보이는 이미지만으로 선택하지 않는다.

### DPF-03 · 콘트라포스토

- 사용자 입력: `한쪽 다리에 힘을 주고 서서 어깨와 골반이 반대로 기운 자세를 찾고 싶어.`
- 기대 선택: `pose_contrapposto` (`pose`)
- 카드 검색 조각: `contrapposto pose` + `standing reference`
- 확인: 지지 다리, 지지 다리 쪽으로 올라간 골반, 반대 방향으로 기운 어깨선이 함께 보이는지 본다.
- 제외: 몸이 휘어 보인다는 설명만 있거나, 두 발에 같은 힘을 준다고 명시한 경우에는 선택하지 않는다.

### DPF-04 · 시팅

- 사용자 입력: `의자에 앉아 있는 캐릭터의 기본 자세를 보고 싶어.`
- 기대 선택: `pose_sitting` (`pose`)
- 카드 검색 조각: `seated pose reference`
- 확인: 골반이 닿는 지지면과 다리·발이 놓이는 방향을 확인한다.
- 제외: 벽에 기대 선 자세나 완전히 누운 자세는 선택하지 않는다.

### DPF-05 · 프론트 뷰

- 사용자 입력: `얼굴과 몸이 보는 사람을 향하는 정면 캐릭터 자료가 필요해.`
- 기대 선택: `view_front` (`view`)
- 카드 검색 조각: `front view`
- 확인: 얼굴·몸통 중앙선과 양쪽 어깨·눈·골반이 비교적 대칭으로 보이는지 본다.
- 제외: 배경의 1점 투시나 카메라 높이 정보만으로 선택하지 않는다.

### DPF-06 · 3/4 뷰

- 사용자 입력: `캐릭터가 정면에서 살짝 돌아선 45도 정도의 모습을 찾고 싶어.`
- 기대 선택: `view_three_quarter` (`view`)
- 카드 검색 조각: `three quarter view`
- 확인: 가까운 쪽 눈·어깨·골반이 조금 더 넓게 보이고, 얼굴 중앙선이 한쪽으로 돌아가는지 본다.
- 제외: 하이 앵글·로우 앵글 정보만 있거나 정면과 측면을 모두 원한다는 모호한 설명에는 선택하지 않는다.

### DPF-07 · 3점 투시

- 사용자 입력: `높은 건물 사이를 내려다보는 듯하고 수직선도 기울어지는 강한 원근 배경을 원해.`
- 기대 선택: `perspective_three_point` (`perspective`)
- 카드 검색 조각: `character` + `three point perspective` + `reference`
- 확인: 가로 방향의 두 소실점과 수직선이 향하는 세 번째 소실점이 함께 성립하는지 본다.
- 제외: 인물을 아래에서 본다는 설명이나 3/4 뷰라는 설명만으로 선택하지 않는다.

### DPF-08 · 과투시/단축법

- 사용자 입력: `손을 카메라 쪽으로 내밀어 가까운 손이 크게 보이는 포즈 자료가 필요해.`
- 기대 선택: `perspective_foreshortening` (`perspective`)
- 카드 검색 조각: `character` + `foreshortening pose reference`
- 확인: 카메라에 가까운 신체 부위와 먼 신체 부위의 크기 차이가 명확한지 본다.
- 제외: 광각 느낌, 하이 앵글, 로우 앵글이라는 정보만으로 선택하지 않는다.

### DPF-09 · 삼분할 구도

- 사용자 입력: `중요한 얼굴을 화면의 삼등분 선이나 교차점 근처에 두는 구도를 보고 싶어.`
- 기대 선택: `composition_rule_of_thirds` (`layout`)
- 카드 검색 조각: `character illustration` + `rule of thirds composition` + `reference`
- 확인: 화면을 가로·세로로 3등분했을 때 얼굴·손·중요 소품이 선 또는 교차점 부근에 놓이는지 본다.
- 제외: 화면을 세 부분으로 나눈다는 말이나 인물이 세 명이라는 말만으로 선택하지 않는다.

### DPF-10 · 구도

- 사용자 입력: `인물과 배경, 빈 공간이 화면에서 어떻게 배치되는지 참고할 구도 자료가 필요해.`
- 기대 선택: `layout_composition` (`layout`)
- 카드 검색 조각: `character illustration` + `composition reference`
- 확인: 인물·배경·빈 공간의 배치와 주된 요소·보조 요소 사이의 시선 관계를 본다.
- 제외: 인물 포즈만 제시했거나 색감·화풍만 언급한 경우에는 선택하지 않는다.

## 검수 전 확인 목록

1. 각 `term_id`가 현재 활성 TERM_CARD인지 확인한다.
2. 검색어 입력은 선택 카드의 `query_fragments`에서만 오며, 사용자 원문·LLM 보완 문구가 섞이지 않는지 확인한다.
3. 정상·검색 0건·검색 실패를 [API 계약](../../specs/api-contract.md)의 결과 규칙에 따라 서로 다르게 주입·조립하는지 확인한다.
4. 실제 검색 결과의 이미지 적합성 평가는 Provider 구현 이후 OSC가 수행하며, 이 초안만으로 외부 이미지 품질을 통과 처리하지 않는다.
