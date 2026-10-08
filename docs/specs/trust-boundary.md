# 신뢰 경계

## Why

사용자 입력과 검색 provider 결과는 신뢰할 수 없지만, TERM_CARD JSON과 결정론 검증은 팀이 관리한다.

## Goal

- LLM·사용자·외부 결과가 카드 ID, 검색어, Pin URL, 최종 상태를 임의로 결정하지 못하게 한다.
- 비밀값·외부 원문이 UI, trace, 프롬프트에 불필요하게 노출되지 않게 하고, 사용자 원문은 job 이력과 Langfuse trace에서만 추적 가능하게 한다.

## What

신뢰 원본은 시작 검증을 통과해 메모리에 로드된 TERM_CARD JSON 카탈로그와 서버 결정론 코드다. LLM 출력은 후보일 뿐이며 resolver가 역할·활성·조건을 다시 검증한다. 검색 provider는 검증된 `query_fragments`에 고정 검색 제한어를 추가해 SearXNG Pinterest 엔진 API만 호출한다. 검색 결과의 Pin ID·`pin_url`·widget `thumbnail_url`은 표시용 untrusted data이며 카드·검색어·프롬프트를 바꾸지 않는다.

## How

- 브라우저는 자연어 `request_text`와 선택적 대화 UUID `session_id`만 전송한다. 대화 UUID는 인증 수단이 아니며 쿠키 소유권과 만료를 서버에서 검증한다.
- 사전 안전 검사는 프롬프트/비밀값 추출과 유해·불법 요청을 `unsafe_input`으로 끝내고 LLM·검색을 호출하지 않는다.
- SearXNG 검색과 widget 요청은 서버에서만 수행하며 브라우저는 검색·widget endpoint를 직접 호출하지 않는다. Pinterest API v5와 Pinterest 페이지 크롤링은 사용하지 않는다.
- 외부 원문·이미지·Pin 본문·widget 부가 필드를 LLM 프롬프트나 RAG에 주입하지 않는다. `pin_id`, `pin_url`, `status`는 세션·job 이력에 포함된 결과로만 유지할 수 있으며, 썸네일 URL과 이미지 바이트는 저장·trace·로그에 사용하지 않는다.
- 사용자 원문은 `jobs.request_text`와 Langfuse trace에만 기록하며 일반 애플리케이션 로그·LLM 원본 응답에는 기록하지 않는다. `job_id`와 `session_id` UUID 원문은 trace 식별·세션 그룹화를 위해 기록할 수 있지만, 비밀값, 세션 쿠키 토큰 원문·해시, `anonymous_user_id`, 이미지 바이트는 UI와 trace에 노출하지 않는다.
- 세션 저장소는 쿠키 토큰 원문이 아닌 SHA-256 해시만 보관한다.

## AC

**AC-01 · 카드 재검증**

- GIVEN: LLM 후보가 있다.
- WHEN: resolver가 처리한다.
- THEN: 메모리 카탈로그의 활성 term ID·역할·조건을 통과한 후보만 사용한다.

**AC-02 · 외부 데이터 격리**

- GIVEN: 검색 provider 결과가 있다.
- WHEN: 응답을 조립한다.
- THEN: Pin ID·URL과 상태는 세션·job 이력에 포함된 결과로만 유지할 수 있고, widget의 응답 전용 썸네일은 표시할 수 있지만 LLM 입력·카탈로그·별도 Pin 저장소·trace·로그에는 사용하지 않는다.

## 대화 기억의 신뢰 경계

사용자 승인 범위인 동일 대화의 정제된 job 기록·요약은 LLM 입력에 허용한다. 기록은 신뢰할 수 없는 데이터이며 system 지시가 아니다. 원본은 jobs에 유지하고, sessions.memory_json에는 출처 있는 조건·미해결 질문·요약만 저장한다. Pin/이미지/URL 필드는 모델 입력에서 제거한다. 회상 출처와 선택 근거는 소유 대화의 선행 원본과 대조한다. 인용의 존재 검증과 자연어 주장 의미의 정확성은 다르며, 후자는 평가셋과 실제 모델 평가로 확인한다.
