# 개인 AI 텀카드 구현 계획

> **상태:** 1~6단계 구현 및 사용자 흐름 검수 완료 · 현재 구현의 설계 기록
>
> **For agentic workers:** 아래 문서는 단계별 구현 당시의 결정과 제약을 보존한다. 후속 변경은 현행 코드·migration·소유권 테스트를 먼저 확인하고 별도 승인을 받는다.

**목표:** 사용자의 자유 입력을 LLM이 개인 용어 초안으로 구조화하고, 사용자 확인 후 소유자 전용 텀카드로 저장하여 그래프 탐색과 반복 검색에 재사용한다.

**아키텍처:** 검수된 공용 JSON 카탈로그는 불변으로 유지하고, PostgreSQL에 소유자별 개인 텀카드 저장소를 별도로 둔다. 프런트와 worker는 요청 소유자의 개인 용어만 공용 카탈로그 위에 일시적으로 합성하며, 전역 카탈로그·MCP 응답·다른 소유자의 화면에는 포함하지 않는다.

**기술 스택:** FastAPI, Pydantic 구조화 출력, PostgreSQL/asyncpg, 기존 LLM transport, Next.js/React, 기존 React/SVG 3D 그래프

## 전역 제약

- 이 문서는 구현 전 계획에서 시작해 현재 구현의 설계 기록으로 갱신됐다. 아래 권장안·미확정 수치는 사용자 승인 없이 새 정책으로 적용하지 않는다.
- 공용 텀카드를 수정·대체·자동 병합하지 않는다.
- 개인 텀카드는 대화 세션이 아니라 `anonymous_owners.owner_id`에 귀속한다.
- 현재 서비스에는 로그인 계정이 없다. 로컬 개인 프로필 또는 익명 소유자 쿠키를 넘어서는 계정·다기기 소유권을 보장하지 않는다.
- LLM 제안은 검증된 공용 전문용어처럼 표시하지 않고 `내 용어 · AI 초안`으로 구분한다.
- LLM 출력은 사용자 확인 전 검색·그래프·일반 대화의 검색 권한이 되지 않는다.
- 개인 노드 추가·선택·삭제·회전 때문에 기존 노드의 월드 좌표를 바꾸지 않는다.
- 개인 노드는 카테고리 허브 하나만 표시 부모로 갖는다.
- 실제 3D 노드 영역과 직선 엣지의 관통은 방지하되, 깊이 차이로 생기는 정상적인 화면 투영 가림은 허용한다.
- 브라우저 자동화 금지가 유지되는 동안 화면 검수는 사용자 수동 검수로 진행한다.
- 새 외부 서비스, 벡터 DB, 인증 제공자 또는 유료 기능을 추가하지 않는다.

---

## 1. 현재 구조에서 확인한 사실

### 공용 카탈로그

- `backend/services/catalog_repository.py`는 JSON 텀카드를 시작 시 검증하여 불변 `CatalogSnapshot`으로 보관한다.
- `frontend/lib/home-catalog.mjs`는 같은 JSON을 번들에 포함하여 활성 82개와 기본 그래프 36개를 만든다.
- 개인 용어를 이 JSON 파일에 쓰면 소유자 격리가 깨지므로 공용 카탈로그 파일은 변경하지 않는다.

### 소유자와 대화

- `backend/db/migrations/003_conversation_owners.sql`은 `anonymous_owners`와 여러 `sessions`의 소유 관계를 정의한다.
- `backend/shared/auth.py`는 HttpOnly `session_id` 쿠키의 원문을, 저장소는 그 SHA-256 해시를 사용한다.
- `backend/local_profile.py`와 `SessionRepository.bind_local_profile()`은 로컬 개인 실행에서 재시작 후에도 같은 소유자를 복원한다.
- 대화 삭제는 session/job 기록의 수명주기다. 개인 텀카드 삭제·복구는 별도 수명주기로 유지해야 한다.

### 검색과 그래프

- `backend/routes/term_search.py`의 `/api/term-search`는 공용 스냅샷만 조회하고 저장된 검색 조각으로 이미지를 찾는다.
- `frontend/components/TermGraph.jsx`는 `terms`와 `catalogTerms`를 별도로 받는다.
- `frontend/lib/term-graph-approved-layout.mjs`의 승인 배치는 고정된 57개 노드 집합을 전제로 한다. 개인 노드를 기존 fallback solver에 섞으면 기존 노드가 움직일 수 있으므로 전용 overlay 배치가 필요하다.

## 2. 사용자 흐름

1. 사용자가 `내 용어 만들기`에서 1~300자의 자유 입력을 작성한다.
2. 서버는 소유자와 idempotency key를 확인한 뒤 LLM 구조화 출력을 한 번 요청한다.
3. UI는 한국어·영어 이름, 카테고리, 설명, 관찰 포인트, 주의점, 한국어 별칭, 영어 검색어, 불확실성을 초안으로 보여 준다.
4. 사용자는 초안을 수정하거나 폐기하거나 저장한다.
5. 저장된 용어는 `active` 상태와 고정 `term_id`·`layout_slot`을 얻는다.
6. 해당 카테고리의 `내 용어` 노드로 그래프와 목록에 나타난다.
7. 사용자는 현재 용어 직접 검색, 선택 조건 전체 검색, 이후 대화의 정확 별칭 재사용을 할 수 있다.
8. 삭제하면 그래프·새 검색에서 빠지지만 대화 기록은 유지된다. 복구하면 같은 ID와 좌표로 다시 나타난다.

`LLM 제안 → 사용자 확인·수정 → 저장` 흐름은 권장안이며 아직 확정 승인이 아니다.

## 3. 개인 저장 모델

구현 시점의 최신 migration 번호를 다시 확인한 뒤 additive migration을 추가한다. 예를 들어 현재 순서라면 `backend/db/migrations/007_personal_terms.sql`이 될 수 있으나, 이 번호는 확정값이 아니다.

단일 `personal_terms` 테이블의 권장 필드:

- `personal_term_id UUID PRIMARY KEY`
- `term_id TEXT UNIQUE`: `personal_<uuid>` 형식의 서버 발급 공개 ID
- `owner_id UUID REFERENCES anonymous_owners(owner_id) ON DELETE CASCADE`
- `status`: `generating`, `proposed`, `active`, `deleted`, `failed`
- `role`: `body`, `pose`, `composition`, `perspective`
- `label_ko`, `label_en`, `plain_meaning_ko`
- `reference_checkpoints_ko JSONB`, `cautions_ko JSONB`
- `aliases_ko JSONB`, `query_fragments_en JSONB`
- `source_input`, `proposal_kind`, `uncertainty_ko`
- `layout_slot`: 카테고리별 고정 배치 번호
- `idempotency_key_hash`, `input_hash`, 생성 시도 횟수
- `created_at`, `updated_at`, `deleted_at`

활성 개수·카테고리별 개수·일일 생성 횟수는 채택되지 않았다. 실제 배치와 LLM 비용을 측정한 뒤 사용자 검수로 결정한다.

## 4. 소유자 경계

모든 저장소 쿼리는 클라이언트가 보낸 owner ID를 받지 않는다. 쿠키 해시 또는 job의 `session_id`에서 서버가 owner를 역조회한다.

| 경로 | 필수 경계 |
| --- | --- |
| 목록·단건 조회 | `anonymous_owners.session_token_hash`와 `personal_terms.owner_id`를 함께 조인 |
| 생성·확정 | 소유자 확인, same-origin 변경 헤더, idempotency key 검증 |
| 수정·삭제·복구 | 소유자 조건을 포함한 단일 SQL에서 대상 확인 |
| 직접 검색 | `active` 상태와 같은 소유자를 다시 확인한 뒤 저장 검색어 사용 |
| 대화 재사용 | `jobs.session_id → sessions.owner_id`를 서버에서 역조회 |

다른 소유자의 ID는 존재 여부를 드러내지 않도록 동일한 `404`로 처리한다. 새 쿠키에서는 다른 소유자의 용어가 보이지 않는다. 현재 로컬 개인 프로필에서는 같은 프로필 토큰으로 모든 대화에서 보인다.

## 5. LLM 구조화 출력과 검증

신규 Pydantic 모델은 다음 필드만 허용한다.

- 네 카테고리 중 하나
- 한국어·영어 이름
- 사용자용 한국어 설명
- 구체적인 관찰 포인트와 주의점
- 한국어 별칭
- 반복 검색에 사용할 영어 검색 조각
- `descriptive`, `coined`, `ambiguous` 중 제안 성격과 한국어 불확실성 안내

사용자 입력은 신뢰할 수 없는 데이터로 JSON 직렬화하여 프롬프트에 넣는다. HTML, URL, Markdown 링크, 제어 문자, 스키마 밖 필드, 빈 설명, 범위를 벗어난 배열은 서버에서 거부한다. React에서는 문자열을 텍스트로만 렌더링하고 `dangerouslySetInnerHTML`을 사용하지 않는다.

`plain_meaning_ko`와 내부 질문·추론을 분리한다. 설명이 없을 때 프롬프트 문장, 내부 단서 질문, `source_input`을 설명 대신 노출하지 않는다.

### 중복·유사 용어

- 공용 또는 활성 개인 용어와 정규화 이름이 정확히 같으면 저장을 차단하고 이름 변경을 요청한다.
- 유사 이름·별칭·검색어는 경고와 비교 대상만 제공한다.
- 사용자가 확인하더라도 별도 개인 용어로 저장하며 기존 용어를 교체하거나 병합하지 않는다.
- 같은 idempotency key와 같은 입력의 재요청은 저장된 생성 상태를 반환하고 LLM을 다시 호출하지 않는다.
- 같은 key에 다른 입력은 `409`로 거부한다.

## 6. 그래프 배치

공용 승인 그래프를 먼저 기존 좌표로 계산한 뒤 개인 노드를 별도 overlay로 합성한다.

- 개인 노드 좌표는 `role + layout_slot + term_id`로 결정한다.
- 슬롯은 저장 시 한 번 배정하고 삭제 후에도 재사용하지 않아 복구 좌표를 보존한다.
- 개인 노드는 해당 카테고리 허브에서 시작하는 직선 하나만 갖는다.
- 개인 노드 표시 여부가 기존 공용 노드·카테고리·확장 자식 좌표에 영향을 주지 않는다.
- 후보 슬롯은 기존 실제 3D 구와 직선 segment의 안전 여유를 검사한다.
- 화면상 투영 교차는 깊이 합성으로 처리하고, 이를 피하려 노드를 화면 좌표에서 따로 움직이지 않는다.
- 안전 슬롯이 부족하면 글자를 줄이거나 기존 노드를 움직이지 않고 목록 전환 안내와 생성 한도 결정을 요청한다.
- 카테고리 색은 유지하되 텍스트 배지·테두리 패턴으로 `내 용어`를 함께 표시한다.

## 7. 검색과 대화 재사용

개인 용어의 이미지 검색은 저장된 `query_fragments_en`을 사용하며 LLM을 다시 호출하지 않는다. 한국어 이름과 `aliases_ko`는 UI, 정확 매칭, 선택 조건 검색에 사용한다.

- `현재 용어 직접 검색`: 개인 term ID를 owner-scoped endpoint로 검색
- `선택 조건 전체 검색`: 공용·개인 선택을 모두 표시하되 각 개인 ID의 소유권을 서버에서 재확인
- `대화 재사용`: worker가 해당 job 소유자의 활성 개인 용어만 임시 catalog overlay에 포함
- 검색은 새로운 chat job을 만들거나 세션당 20회 메시지 한도를 차감하지 않음
- 검색 실패 재시도는 기존 저장 검색어를 재사용하며 새 LLM 생성을 하지 않음
- 삭제된 용어는 새 검색·새 선택에서 거부하고, 과거 대화는 당시 결과 스냅샷만 표시

## 8. 삭제·복구와 실패 처리

- 개인 용어 삭제는 soft delete다. 대화 삭제 API와 결합하지 않는다.
- 삭제 중 진행 중인 검색은 요청 시작 시 확인한 owner와 term ID를 유지하되, 결과를 현재 그래프에 자동 복원하지 않는다.
- 복구는 같은 term ID와 layout slot을 사용한다. 활성 정확 중복이 생겼으면 `409`와 충돌 용어를 반환한다.
- LLM timeout·형식 오류에는 활성 용어를 만들지 않는다.
- `failed` 제안의 명시적 재시도만 허용하며, 무한 자동 재시도는 하지 않는다.
- 빠른 반복 확인·수정·삭제는 idempotency와 상태 전이 조건으로 중복 저장을 막는다.
- 프런트는 대화/화면 전환 generation 값을 확인하여 늦은 제안 응답이 현재 편집 화면을 덮지 않게 한다.

## 9. 예상 파일 경계

### 현재 확인된 연결 파일

- `backend/services/catalog_repository.py`: 공용 불변 카탈로그
- `backend/services/session_repository.py`: 익명 소유자·세션 관계
- `backend/routes/term_search.py`: 공용 직접 검색
- `backend/services/agent_worker.py`: 대화별 LLM 해석·검색 흐름
- `frontend/lib/home-catalog.mjs`: 공용 프런트 카탈로그
- `frontend/lib/term-graph.mjs`: 고정 3D 그래프 계산
- `frontend/components/TermGraph.jsx`: 그래프·목록 표시
- `frontend/app/page.jsx`: 서비스 화면 상태와 검색 연결

### 구현 시 제안하는 신규 파일

- `backend/schemas/personal_terms.py`: API·LLM 구조화 모델
- `backend/services/personal_term_repository.py`: owner-scoped 상태 전이와 CRUD
- `backend/services/personal_term_generator.py`: 단발 구조화 생성
- `backend/services/term_search_service.py`: 공용·개인 검색 실행부 공유
- `backend/routes/personal_terms.py`: 제안·확정·조회·수정·삭제·복구·검색 API
- `frontend/lib/personal-terms.mjs`: API 호출과 응답 검증
- `frontend/components/PersonalTermCreator.mjs`: 초안 검토·수정·확정 UI
- `frontend/lib/term-graph-personal-layout.mjs`: 고정 개인 노드 슬롯

기존 파일 수정은 각 단계 수용 테스트가 요구하는 최소 연결만 수행한다. 구현 당시 저장소 상태와 migration 순서를 다시 확인한다.

## 10. 단계별 구현 계획

### 단계 1: 소유자별 저장소와 CRUD

- [ ] 소유자 A/B 격리, 상태 전이, idempotency를 검증하는 실패 테스트를 먼저 추가한다.
- [ ] 최신 번호를 확인한 additive migration과 repository를 구현한다.
- [ ] 조회·제안 레코드 생성·확정·수정·soft delete·복구를 owner-scoped SQL로 구현한다.
- [ ] 공용 카탈로그와 기존 세션/대화 삭제 동작이 변하지 않았음을 확인한다.
- [ ] 사용자 검수 후 단계 2 승인을 기다린다.

### 단계 2: LLM 제안 생성

- [ ] 엄격한 구조화 출력, prompt injection, HTML/URL, 빈 설명, timeout, 동일 key 재시도 테스트를 추가한다.
- [ ] 기존 `codex-cli`/OpenRouter 설정을 따르는 개인 용어 생성기를 구현한다.
- [ ] 유사 후보를 결정론적으로 계산하되 자동 병합하지 않는다.
- [ ] 생성 성공은 `proposed`, 실패는 `failed`까지만 만들고 그래프·검색에는 노출하지 않는다.
- [ ] 사용자 검수 후 단계 3 승인을 기다린다.

### 단계 3: 확인·저장 UI

- [ ] 프런트 API 응답 검증과 늦은 응답 무시 테스트를 추가한다.
- [ ] 자유 입력, 생성 상태, 초안 필드 수정, 중복 경고, 명시적 저장 UI를 구현한다.
- [ ] 저장된 개인 용어 목록과 수정·삭제·복구 조작을 추가한다.
- [ ] AI 초안·개인 용어 표시가 색상 외 텍스트로도 전달되는지 확인한다.
- [ ] 사용자 검수 후 단계 4 승인을 기다린다.

### 단계 4: 고정 3D 그래프 통합

- [ ] 개인 용어 추가 전후 모든 기존 월드 좌표가 동일한 RED 테스트를 추가한다.
- [ ] 각 개인 노드가 카테고리 부모 하나와 고정 슬롯을 갖는 layout overlay를 구현한다.
- [ ] 노드 구 충돌, 직선-무관 노드 구 관통, 회전 깊이, 삭제·복구 좌표 불변을 검사한다.
- [ ] 안전 용량을 측정하고 그 결과를 사용자에게 제시한 뒤 실제 한도를 결정한다.
- [ ] 사용자 검수 후 단계 5 승인을 기다린다.

### 단계 5: 검색과 대화 재사용

- [ ] 개인 term ID를 다른 owner가 검색할 수 없는 API 테스트를 추가한다.
- [ ] 공용·개인 검색의 provider 호출부를 공유 서비스로 분리한다.
- [ ] 직접 검색과 선택 조건 전체 검색에 개인 용어를 연결한다.
- [ ] job의 owner별 개인 catalog overlay를 대화 해석에 전달한다.
- [ ] 검색 재사용이 LLM 생성·chat job·20회 한도를 증가시키지 않는지 확인한다.
- [ ] 사용자 검수 후 단계 6 승인을 기다린다.

### 단계 6: 오류·보안·회귀

- [ ] 두 소유자, 새 대화, 새 쿠키, 로컬 프로필 재시작, 빠른 연속 요청을 격리 DB에서 검증한다.
- [ ] 생성 실패·재시도·확정 중복·검색 실패·삭제 중 응답·복구 충돌을 검증한다.
- [ ] 기존 공용 82개 카탈로그, 그래프, 검색, 기록, 세션 한도 전체 회귀를 실행한다.
- [ ] 사용자 데이터나 운영 DB를 초기화하지 않고 additive migration 호환성을 확인한다.
- [ ] 최종 사용자 검수와 별도 반영 승인을 기다린다.

## 11. 수용 기준

- 소유자 A의 개인 용어는 소유자 B의 모든 조회·검색·수정·삭제 경로에서 보이지 않는다.
- 같은 소유자의 새 대화에서는 개인 용어가 유지되고, 다른 쿠키에서는 보이지 않는다.
- 사용자 확인 전 LLM 제안은 그래프·검색·대화 선택에 포함되지 않는다.
- 공용 또는 개인 유사용어가 있어도 자동 대체·병합되지 않는다.
- 설명 필드에는 내부 질문·프롬프트·추론이 나타나지 않는다.
- 개인 노드 추가·선택·삭제·복구 전후 기존 노드 월드 좌표가 동일하다.
- 개인 노드의 표시 부모는 정확히 하나이며 카테고리와 일치한다.
- 실제 3D 노드 충돌과 직선 엣지의 무관한 노드 관통이 없고 정상 깊이 가림은 유지된다.
- 직접 검색과 선택 조건 검색은 저장된 검색어를 사용하고 LLM을 호출하지 않는다.
- 개인 용어 삭제와 대화 삭제는 서로의 데이터를 삭제하지 않는다.
- 복구 후 같은 term ID와 layout slot을 사용한다.
- 기존 공용 카탈로그·1~7단계 UX·세션당 메시지 한도가 회귀하지 않는다.

## 12. 미확정 사용자 결정

1. **소유권 범위**
   - 권장: 현재 로컬 개인 프로필/익명 소유자 단위로 먼저 구현
   - 공개·다기기 계정이 필요하면 로그인 인증을 별도 선행
2. **저장 흐름**
   - 권장: AI 초안 확인·수정 후 명시적으로 저장
   - 대안: 생성 즉시 저장
3. **용량·생성 한도**
   - 활성 개수, 카테고리별 개수, 생성 빈도 모두 그래프 배치·성능·LLM 비용 측정 후 결정

이 문서는 위 결정을 확정하지 않는다. 사용자가 다른 작업을 먼저 진행하므로 기능 구현은 명시적인 재개 지시가 있을 때까지 보류한다.
