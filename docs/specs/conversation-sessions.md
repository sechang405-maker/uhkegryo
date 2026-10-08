# 대화 소유권과 재접속
## Why
익명 사용자는 여러 대화를 분리하고 재접속 후에도 같은 기록을 사용해야 한다. 격리·기존 기록 보존 AC 통과가 지표다.
## Goal
쿠키 소유자와 대화를 분리하고 생성·목록·열람·이력 API를 제공한다. 로그인, UI, 기기 간 복구는 제외한다.
## What
새 대화를 만들고 session_id로 요청한다. 생략 시 기본 대화를 사용한다. 소유권 없는/만료된 대화는 404, 유효 쿠키 없는 조회는 401이다. 목록·polling·이력 조회는 대화 수명을 연장하지 않는다. 대화 열기와 성공적으로 접수된 메시지만 갱신한다.
## How
anonymous_owners(owner_id UUID, session_token_hash UNIQUE, default_session_id nullable FK SET NULL)를 추가한다. 기존 sessions의 UUID/hash를 owner로 이관하고 sessions.owner_id FK를 추가한다. 기존 jobs/session UUID는 보존한다. 원문 token은 저장하지 않는다.
expires_at은 last_activity_at + interval '3 months'이며 now() >= expires_at이면 만료다. 만료 확인 전에 touch하지 않는다. 쿠키 Max-Age도 UTC 달력의 3개월을 월말 보정해 계산한다.
POST /api/sessions는 201과 session_id/created_at/last_activity_at/expires_at을 반환한다. 첫 대화가 기본 대화다.
GET /api/sessions는 limit(1..100, 기본20), offset(기본0)으로 최근 활동 역순 목록 items를 반환한다.
GET /api/sessions/{id}는 열람 갱신 후 대화 메타데이터를 반환한다.
GET /api/sessions/{id}/jobs는 limit/offset으로 (created_at,job_id) 오름차순 items(request_text,created_at,job envelope)를 반환한다.
POST /api/agent는 request_text와 선택적 UUID session_id만 허용한다. 명시한 ID 실패 시 기본 대화로 fallback하지 않는다. 신규 소유자·기본 대화·job은 같은 transaction에서 생성한다. 기존 소유자의 동시 기본 대화 생성은 owner lock으로 직렬화한다. 동일 대화 idempotency 10분 규칙은 유지한다.
GET /api/jobs/{id}는 owner→미만료 session→job으로 검사한다. 쿠키 갱신은 DB 대화 touch와 분리한다.
migration은 자동 운영 적용하지 않는다. 로컬 격리 테스트 DB에서만 적용한다.
## AC
- Given 기존 cookie와 job, When migration, Then 동일 cookie/UUID로 조회 가능하다.
- Given 한 소유자의 A/B와 다른 소유자의 C, When 조회·제출, Then A/B만 접근 가능하고 C는404다.
- Given 만료 시각, When 조회·제출·worker claim, Then 만료 대화를 사용하지 않는다.
- Given 목록/polling/이력 조회, When 수행, Then last_activity_at은 변하지 않는다.
- Given 같은 소유자의 동시 기본 제출, When 접수, Then 기본 대화는 하나이고 중복 key는 기존 job이다.
