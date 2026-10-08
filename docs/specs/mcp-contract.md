# TERM_CARD JSON FastMCP 계약

## Why

도메인 용어의 설명·검색 조각은 LLM이 추정해서 만들면 안 된다. 검증된 활성 카드만 가져오는 도구를 별도 경계로 두어 Agent의 근거 원본을 고정한다.

## Goal

- FastMCP가 `get_active_term_card(term_id)`와 `search_pinterest_pins(role, query_fragments)`를 `/mcp` Streamable HTTP endpoint로 제공한다.
- 도구의 유일한 카드 원본은 시작 검증을 통과해 메모리에 로드된 TERM_CARD JSON 카탈로그다.
- 브라우저는 MCP에 직접 연결하지 않고, 검증된 Agent worker만 도구를 호출한다.

## What

`get_active_term_card` 입력은 `term_id: str` 하나이며, 활성 카드 한 건의 읽기 전용 복사본만 반환한다. `search_pinterest_pins`는 역할과 검색 조각 배열을 입력받는다. 검색 도구는 역할과 조각 전체가 활성 TERM_CARD와 정확히 일치할 때만 SearXNG를 호출한다.

성공 응답은 다음 정보를 포함한다.

```json
{
  "status": "found",
  "catalog_version": "<index.dataset_version>",
  "term": {
    "term_id": "pose_contrapposto",
    "role": "pose",
    "label_ko": "콘트라포스토",
    "label_en": "contrapposto",
    "query_fragments": ["contrapposto pose", "standing reference"],
    "look_for": ["한 다리에 체중이 실림", "골반과 어깨가 반대 방향으로 기울어짐"]
  }
}
```

비활성·존재하지 않는 ID는 `{"status":"not_found","reason_code":"TERM_NOT_ACTIVE"}`를 반환한다. 카탈로그 시작 검증에 실패하면 MCP는 ready 상태가 되지 않으며 `CATALOG_INVALID_AT_STARTUP`을 운영 원인으로 기록한다. 호출자에게 원시 파일 경로·비활성 카드·내부 오류 원문은 반환하지 않는다.

## How

- FastMCP 시작 시 `term-card-catalog.md`의 검증을 실행하고, 성공한 활성 카드 사전을 읽기 전용 메모리로 보관한다.
- FastAPI 엔트리포인트에 Streamable HTTP 앱을 마운트할 때 부모 앱의 lifespan에서 FastMCP session manager를 시작하고 종료한다. 마운트된 자식 앱의 lifespan 자동 실행에 의존하지 않는다.
- DNS rebinding 방어를 유지하면서 로컬 Host(`127.0.0.1`, `localhost`, `[::1]`)와 `MCP_ALLOWED_HOST`에 지정한 Cloud Run Host만 Streamable HTTP 요청에 허용한다. Cloud Run IAM 인증은 별도로 계속 적용한다.
- `get_active_term_card`의 description에는 “Pydantic 검증 뒤의 활성 term ID에 대한 팀 검수 설명·검색 조각이 필요할 때 사용한다”를 명시한다.
- `/mcp`는 서비스 토큰 또는 허용된 서비스 클라이언트만 연결할 수 있게 설정한다. Next.js UI와 일반 브라우저의 직접 호출은 허용하지 않는다.
- `search_pinterest_pins`는 전달된 role·`query_fragments`가 활성 카탈로그의 한 카드와 정확히 일치하지 않으면 `INVALID_SEARCH_TERMS`로 반환하고 SearXNG를 호출하지 않는다.
- 검색 도구는 유효 조각에 `drawing`을 덧붙여 SearXNG Pinterest 엔진만 검색하고, Pin ID 기반 canonical Pin URL을 검증한다.
- 전체 레퍼런스 교체에는 선택적 `exclude_pin_ids`(null 또는 최대 40개 숫자 문자열)를 받는다. worker가 직전 보드의 결과에서 주입하며, 제외 후 8개 상한을 적용한다. 상세 계약은 reference-refresh.md를 따른다.
- 구현 완료 시 README에 `/mcp` 연결 방법, tool 목록, 인증 방식, `found`·`not_found` 실제 호출 결과를 추가한다.

## AC

**AC-01 · 활성 카드만 반환**

- GIVEN: 시작 검증을 통과한 활성 카드가 있다.
- WHEN: worker가 해당 `term_id`로 도구를 호출한다.
- THEN: 도구는 해당 카드의 허용 필드만 구조화해 반환한다.

**AC-02 · 비활성 카드 차단**

- GIVEN: 없는 ID 또는 활성 조건을 만족하지 않는 ID가 있다.
- WHEN: 도구를 호출한다.
- THEN: `TERM_NOT_ACTIVE`와 함께 `not_found`를 반환하고 검색 provider를 호출하지 않는다.

**AC-03 · 카탈로그 fail-closed**

- GIVEN: JSON 카탈로그의 구조 검증이 실패한다.
- WHEN: FastMCP를 시작한다.
- THEN: `/mcp`와 Agent worker는 ready 상태가 되지 않는다.

**AC-04 · 접근 및 호출 증거**

- GIVEN: 배포된 서비스가 있다.
- WHEN: 허용된 MCP client가 `/mcp`에 연결한다.
- THEN: `get_active_term_card` 목록과 실제 `found`·`not_found` 호출 결과를 README와 데모에 남긴다.

**AC-05 · 마운트된 MCP session manager**

- GIVEN: `backend.mcp.main:app`의 카탈로그 시작 검증이 성공했다.
- WHEN: FastAPI lifespan 안에서 별도 Streamable HTTP client가 `/mcp`를 초기화하고 도구를 호출한다.
- THEN: session manager가 준비돼 HTTP 500 없이 `get_active_term_card`의 `found`·`not_found` 결과를 반환한다.

**AC-06 · 허용된 Host에서 Streamable HTTP 요청**

- GIVEN: Cloud Run Host가 `MCP_ALLOWED_HOST`에 지정되어 있고 IAM 인증을 통과했다.
- WHEN: MCP client가 해당 Host로 `/mcp`를 호출한다.
- THEN: DNS rebinding 검증이 요청을 `421`로 거부하지 않고 도구 호출을 처리한다.

**AC-07 · 검색 입력을 활성 TERM_CARD로 제한**

- GIVEN: 활성 카드의 역할과 `query_fragments`가 일치한다.
- WHEN: `search_pinterest_pins`가 호출된다.
- THEN: SearXNG 검색을 수행한다.
- AND GIVEN: 역할 또는 조각 배열이 활성 카드와 일치하지 않는다.
- AND WHEN: 같은 도구가 호출된다.
- THEN: `INVALID_SEARCH_TERMS`를 반환하고 SearXNG를 호출하지 않는다.
