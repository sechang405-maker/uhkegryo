# PostgreSQL Job Worker

## Why

별도 큐 없이도 비동기 Agent job을 안전하게 실행하고, worker 중단이나 일시적 외부 장애 뒤에 중복 처리 없이 회복해야 한다.

## Goal

- PostgreSQL `jobs`를 polling queue로 사용한다.
- 전체 동시 실행은 기본 5개이며 같은 세션에서는 하나만 실행한다.
- worker 중단 job은 최대 3회 안에서 재실행한다.

## What

worker는 1초마다 `attempt < max_attempts`이고 `next_retry_at IS NULL OR next_retry_at <= now()`인 queued job 또는 lease가 만료된 비종결 진행 job(`running | validating | searching | rendering`)을 찾는다. 새 job은 `attempt=0`, `next_retry_at=null`로 생성되며, claim transaction이 `attempt`를 1 증가시키고 status를 `running`으로 바꾸며 30초 lease를 설정한다. lease가 만료된 `attempt=max_attempts` 진행 job은 claim하지 않고 `JOB_INSTANCE_INTERRUPTED`로 `failed` 처리한다. `completed`·`failed`와 결정적 오류로 `failed` 처리된 job은 복구하지 않는다. 실행 중 10초마다 heartbeat로 lease를 30초 뒤로 연장한다.

같은 session의 queued job은 더 이른 미종결 job이 있으면 claim하지 않는다. lease 만료 job은 중간 실행을 이어가지 않고 처음부터 재실행하며 `attempt`를 1 증가한다. `attempt=3` 뒤 회복 가능한 실패는 `failed`와 `JOB_INSTANCE_INTERRUPTED` 또는 실제 최종 failure code로 종결한다.

## How

- claim은 `FOR UPDATE SKIP LOCKED` transaction으로 수행해 worker 둘이 같은 job을 얻지 못하게 한다.
- `WORKER_CONCURRENCY` 기본값은 5이며 worker가 동시에 보유한 lease 수를 제한한다.
- worker는 첫 실행에서 `queued → running → validating → searching → rendering → completed|failed`로 전이하고, 회복 가능한 오류에서는 실행 중 상태에서 `queued`로 되돌린다.
- worker는 claim 결과의 `attempt`를 모든 상태 전이와 완료·실패 저장에 함께 전달한다. 저장은 현재 DB 행의 `attempt`와 일치할 때만 허용된다. lease recovery 뒤 이전 attempt의 worker가 `StaleJobAttempt`를 받으면 이를 정상적인 fencing 신호로 처리하고 해당 실행을 중단한다. stale write는 사용자 failure를 만들거나 재시도를 예약하지 않는다.
- LLM 회복 가능 오류에서만 `attempt<3`이면 lease를 제거하고 `next_retry_at`을 LLM 오류별 backoff 뒤 시각으로 설정한 뒤 `queued`로 되돌린다. worker polling은 그 시각 전에는 claim하지 않으며, 다음 claim이 attempt를 증가시켜 처음부터 재실행한다. LLM 오류의 분류·backoff·구조화 출력 재요청은 [openrouter-llm-adapter.md](./openrouter-llm-adapter.md)가 단일 기준이다. crawler·widget은 worker의 `next_retry_at` 재큐잉 대상이 아니며, 결과 경로는 [pinterest-widget-crawler.md](./pinterest-widget-crawler.md)의 `partial_result`·`deleted` 규칙을 따른다. `attempt=3`이면 실제 failure code로 `failed` 처리한다. 구성·DB migration·코드 오류는 즉시 `failed`다.
- 완료·실패 저장에 성공한 뒤 lease를 제거한다.

## AC

- GIVEN: queued job 두 개가 같은 세션에 있다, WHEN: worker가 claim, THEN: 먼저 생성된 job만 running이 된다.
- GIVEN: 서로 다른 세션의 queued job 여섯 개, WHEN: 기본 worker가 polling, THEN: 동시에 running인 job은 최대 다섯 개다.
- GIVEN: running job의 heartbeat가 10초마다 성공, WHEN: 30초가 경과, THEN: lease는 만료되지 않는다.
- GIVEN: worker가 heartbeat 없이 중단, WHEN: 30초 lease가 만료, THEN: 다른 worker는 attempt를 1 증가해 job을 처음부터 재실행한다.
- GIVEN: 세 번째 attempt가 회복 가능한 오류로 끝남, WHEN: worker가 종결, THEN: job은 failed이며 더 이상 claim되지 않는다.
- GIVEN: 첫 LLM timeout이 12:00:00에 발생, WHEN: worker가 job을 queued로 되돌린다, THEN: `next_retry_at=12:00:01`이고 12:00:01 전 polling은 해당 job을 claim하지 않는다.
- GIVEN: attempt 1의 lease가 만료된 뒤 attempt 2가 job을 claim했다, WHEN: 늦게 복귀한 attempt 1 worker가 상태 전이를 저장한다, THEN: 저장은 `StaleJobAttempt`로 거부되고 attempt 2의 상태와 결과는 바뀌지 않는다.
- GIVEN: worker가 상태 저장에서 `StaleJobAttempt`를 받았다, WHEN: 해당 worker 실행을 중단한다, THEN: 사용자 failure를 새로 만들거나 재시도를 예약하지 않는다.

## 대화 기억 변경

대화 기억 확장: 만료된 대화는 claim하지 않는다. 저장된 기억 구성·필요한 회상 후 일반 해석을 수행하고, 회상 전용이면 searching을 생략한다. 완료 상태와 memory_json은 같은 transaction에서 attempt 및 세션 만료를 검사해 저장한다. 요약은 conversation-summary-background.md의 별도 루프에서 갱신하며 실패가 답변 재시도를 만들지 않는다.
