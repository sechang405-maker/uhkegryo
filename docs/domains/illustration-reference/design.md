# Illustration Reference Agent Design

현재 구현 기준은 `docs/PRD.md`, `docs/SDD.md`, `docs/specs/api-contract.md`, `docs/specs/term-card-catalog.md`, `docs/specs/mcp-contract.md`다. TERM_CARD는 역할별 JSON 카탈로그를 시작 시 검증해 FastMCP 프로세스의 메모리에 로드하며 DB에 적재하지 않는다.

LLM은 활성 term ID 후보와 근거만 만든다. Pydantic과 결정론 resolver가 후보를 검증한 뒤 `get_active_term_card(term_id)`로 활성 카드만 받는다. 서버는 반환 카드의 조건을 다시 검증하고 `query_fragments`에 고정 제한어를 붙여 SearXNG Pinterest 엔진을 호출한다. 반환 URL에서 유효한 Pinterest Pin ID만 추린 뒤 widget endpoint로 조회한다. 사용자 의미 상태와 Pin 상태는 API 계약의 enum만 사용한다. `thumbnail_url`은 응답 전용이며 `pin_id`, `pin_url`, `status`만 세션·job 이력에 포함한다.
