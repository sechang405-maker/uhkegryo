# Pinterest Widget Crawler Documentation Implementation Plan

> **Historical plan:** 이 문서는 2026-09-23 작업 계획 기록이다. 현재 구현 계약은 [`pinterest-widget-crawler.md`](../../specs/pinterest-widget-crawler.md)와 [`session-job-persistence.md`](../../specs/session-job-persistence.md)만 사용한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 승인된 서버 측 Pinterest 크롤링과 widget 기반 이미지 URL 조회를 모든 제품 문서의 단일 계약으로 정렬한다.

**Architecture:** Playwright 검색 크롤러가 활성 TERM_CARD 검색 조각으로 Pin ID·`pin_url`을 수집한다. 모든 ID는 widget endpoint로 조회해 응답 전용 `thumbnail_url`을 얻으며, 세션·job 이력에는 결과의 `pin_url`·`status`만 포함한다.

**Tech Stack:** Python Playwright, FastAPI worker, Next.js UI, Pinterest widget endpoint, TERM_CARD JSON.

**Spec:** `docs/specs/pinterest-widget-crawler.md`

## Global Constraints

- Pinterest API v5와 `GET /v5/pins/{pin_id}`는 사용하지 않는다.
- crawler와 widget 요청은 서버에서만 수행하며 브라우저는 직접 호출하지 않는다.
- widget의 `thumbnail_url`과 이미지 바이트는 저장·LLM 입력·trace·로그에 사용하지 않는다.
- 세션·job 이력에는 결과의 `pin_url`과 `status`만 포함하고 별도 Pin 저장소·캐시·이미지 프록시를 만들지 않는다.
- 검색·widget 일시 오류는 최초 실행 포함 최대 3회 자동 재시도하고, 소진 뒤 유효 카드가 있으면 `completed + partial_result`와 `PIN_SEARCH_UNAVAILABLE`을 반환한다.

## Review Focus

- widget 응답이 이미지 URL을 하나도 주지 않아도 `pin_url` 링크와 `thumbnail_unavailable` 상태를 유지한다.
- widget 요청 자체가 timeout·차단·형식 오류이면 이미지 부재와 구분해 `PIN_SEARCH_UNAVAILABLE`으로 처리한다.
- `thumbnail_url`이 세션·job 이력, trace, 로그에 저장되지 않는다.
- 활성 카드의 `query_fragments` 밖 문자열이 검색 URL에 들어가지 않는다.
- 기존 문서 어디에도 “Pinterest 크롤링은 범위 밖” 또는 “provider 승인 전 구현 불가” 표현이 남지 않는다.

---

### Task 1: 제품 범위와 아키텍처 문서 정렬

**Files:**
- Modify: `README.md`
- Modify: `NOT_BUILD.md`
- Modify: `docs/PRD.md`
- Modify: `docs/SDD.md`

**Interfaces:**
- Consumes: `docs/specs/pinterest-widget-crawler.md`의 crawler·widget·저장 제약
- Produces: 제품 범위와 컴포넌트 다이어그램의 `PinterestCrawlerProvider` 계약

- [x] **Step 1: 기존 금지·보류 표현 확인**

Run: `rg -n "크롤링.*범위 밖|검색 제공자 확정|승인된 provider|PinterestSearchProvider" README.md NOT_BUILD.md docs/PRD.md docs/SDD.md`

Expected: 기존 Pinterest API 보류와 크롤링 금지 표현을 확인한다.

- [x] **Step 2: 제품 범위 문서 수정**

`README.md`와 `NOT_BUILD.md`에서 “Pinterest 크롤링은 하지 않음”과 “provider 미확정”을 제거한다. 이미지 파일·`thumbnail_url` 비저장, 세션·job 이력의 `pin_url`·`status` 유지, Pinterest API v5 미사용은 유지한다.

- [x] **Step 3: PRD·SDD 아키텍처 수정**

`docs/PRD.md`와 `docs/SDD.md`에서 Search provider를 서버 측 `PinterestCrawlerProvider`로 명시한다. 활성 카드 검색 조각 → 공개 검색 크롤링 → Pin ID widget 조회 → 응답 전용 이미지 URL의 흐름과 `partial_result` 경계를 Spec과 같은 문구로 반영한다.

- [x] **Step 4: 문서 계약 검사**

Run: `rg -n "크롤링.*범위 밖|검색 제공자 확정|승인된 provider" README.md NOT_BUILD.md docs/PRD.md docs/SDD.md`

Expected: 0건.

- [x] **Step 5: Commit**

```bash
git add README.md NOT_BUILD.md docs/PRD.md docs/SDD.md
git commit -m "docs: adopt pinterest widget crawler"
```

### Task 2: 런타임·보안·작업 계약 정렬

**Files:**
- Modify: `docs/specs/api-contract.md`
- Modify: `docs/specs/mcp-contract.md`
- Modify: `docs/specs/trust-boundary.md`
- Modify: `docs/work-tickets.md`
- Modify: `docs/domains/illustration-reference/design.md`
- Modify: `docs/domains/illustration-reference/competitive-analysis.md`
- Modify: `skills/SKILL.md`

**Interfaces:**
- Consumes: `PinterestCrawlerProvider.search(query_fragments) -> PinResult[]`의 Spec 규칙
- Produces: API·보안·도메인 문서에서 동일한 외부 데이터와 오류 경계

- [x] **Step 1: API와 신뢰 경계 수정**

`api-contract.md`에 widget endpoint가 서버 측 provider의 기본 이미지 URL 조회임을 연결한다. `mcp-contract.md`의 후속 검색 호출을 `PinterestCrawlerProvider`로 바꾼다. `trust-boundary.md`에 Pin ID·`pin_url`·`status`의 세션·job 결과 보관과 `thumbnail_url`·이미지·widget 부가 필드의 비저장·비LLM 입력을 명시한다.

- [x] **Step 2: 실행 책임 문서 수정**

`work-tickets.md`, 도메인 설계·경쟁 분석, `skills/SKILL.md`에서 “크롤링 범위 밖”을 제거하고 활성 `query_fragments`만 쓰는 서버 crawler와 widget 조회를 명시한다. 브라우저 직접 호출·자유 검색어·외부 본문 LLM 주입 금지는 유지한다.

- [x] **Step 3: 정책 상충 검사**

Run: `rg -n "크롤링.*범위 밖|PinterestSearchProvider|승인된 provider|thumbnail_url.*저장|이미지.*LLM" README.md NOT_BUILD.md docs skills`

Expected: 허용된 crawler 계약만 남고, 금지·저장 정책은 Spec과 모순되지 않는다.

- [x] **Step 4: Commit**

```bash
git add docs/specs/api-contract.md docs/specs/mcp-contract.md docs/specs/trust-boundary.md docs/work-tickets.md docs/domains/illustration-reference/design.md docs/domains/illustration-reference/competitive-analysis.md skills/SKILL.md
git commit -m "docs: align crawler runtime boundaries"
```

### Task 3: 최종 문서 검증

**Files:**
- Verify: `docs/**/*.md`
- Verify: `docs/domains/illustration-reference/term-cards/*.json`

**Interfaces:**
- Consumes: Task 1·2의 문서 계약
- Produces: 구현 착수 가능한 일관된 문서 상태

- [x] **Step 1: Spec 형식·JSON 검증**

Run:

```powershell
$specs = Get-ChildItem docs/specs -File -Filter '*.md' | Where-Object { $_.Name -ne '_example.md' }
foreach ($spec in $specs) { $text = Get-Content -Raw $spec.FullName; foreach ($heading in @('## Why', '## Goal', '## What', '## How', '## AC')) { if ($text -notmatch [regex]::Escape($heading)) { throw "Missing $heading in $($spec.Name)" } } }
Get-ChildItem docs/domains/illustration-reference/term-cards -File -Filter '*.json' | ForEach-Object { Get-Content -Raw $_.FullName | ConvertFrom-Json | Out-Null }
git diff --check
```

Expected: 모든 활성 Spec이 다섯 섹션을 갖고 JSON과 diff 검사가 통과한다.

- [x] **Step 2: 금지 정책 잔존 검사**

Run: `rg -n "Pinterest 크롤링은.*범위 밖|검색 제공자 확정|승인된 provider 계약" README.md NOT_BUILD.md docs skills`

Expected: 0건.

- [x] **Step 3: Commit 검증 결과**

```bash
git status --short
git log --oneline -2
```

Expected: 작업 트리가 깨끗하고 Task 1·2의 정책 커밋이 존재한다.
