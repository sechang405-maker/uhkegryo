# 해석 검증 오류 처리

## Why

- **페르소나**: 자연어로 레퍼런스를 요청하는 사용자와 이를 운영하는 개발자.
- **상황**: 모델의 구조화 응답은 worker가 검증하며 실패는 job attempt 정책으로 처리한다.
- **문제**: 검증 실패 후 내부 재호출과 사용자 원문·모델 후보를 system 메시지에 넣으면 호출 상한과 신뢰 경계가 깨진다.
- **측정 지표**: job당 provider 호출은 최초 호출 포함 최대 3회이며, 한 attempt의 호출은 1회다.

## Goal

- 검증 실패를 내부에서 반복 호출하지 않고 기존 `JobRetryRecovery` attempt 정책에 맡긴다.
- 사용자 원문은 기존 user 메시지에만 두고 system에는 고정 규칙만 전달한다.
- `InterpretationOutput` enum과 프롬프트 출력 상태를 일치시킨다.
- **Out of Scope**: 해석 스키마 상태 확장, 검증 기준 완화, 호출 재시도 상한 변경.

## What

**Happy Path**
1. Worker가 한 attempt에서 해석 provider를 한 번 호출한다.
2. 유효한 구조화 출력은 resolver 검증으로 진행한다.
3. 구조화 검증 오류는 attempt 실패가 되어 기존 recovery가 재시도 여부를 결정한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 구조화 출력 오류 | 해당 attempt 실패로 전달하고 내부 재호출하지 않음 |
| EC-02 | 최대 attempts 도달 | 기존 recovery 계약대로 job 종료 |
| EC-03 | 중복 역할 출력 | 고정 규칙만 사용하고 모델 후보 ID를 system에 재삽입하지 않음 |
| EC-04 | 근거 인용 오류 | 원문을 system에 복사하지 않고 user 메시지 원문만 근거로 유지 |
| EC-05 | 범위 밖 요청 | 서버 측 판정으로 처리하고 LLM enum 상태로 요구하지 않음 |

## How

- `AgentJobWorker`의 correction loop를 제거한다. provider는 attempt당 1회, 기본 최대 3 attempt다.
- 교정 helper는 요청 텍스트와 오류 raw input을 인자로 받지 않는다. 출력 문구는 고정 규칙뿐이다.
- adapter 해석 요청은 system/user 두 메시지만 사용하며 별도 correction system 메시지를 추가하지 않는다.
- `interpretation_state`는 `select_terms | needs_clarification`만 모델 출력으로 허용한다. 범위 밖 요청은 서버 판정으로 유지한다.

## AC (Given-When-Then)

**AC-01 · attempt별 provider 호출 상한**
- GIVEN: 구조화 출력이 검증에 실패한다.
- WHEN: worker가 한 attempt를 처리한다.
- THEN: provider를 정확히 한 번 호출하고 실패를 recovery 정책에 전달한다.

**AC-02 · job 호출 상한**
- GIVEN: 세 번의 worker attempt가 모두 실행된다.
- WHEN: 각 attempt에서 해석 provider 호출 수를 합산한다.
- THEN: 총 호출 수는 최대 3회다.

**AC-03 · 사용자 원문 신뢰 경계**
- GIVEN: 원문 근거 검증 오류가 발생한다.
- WHEN: adapter 요청을 구성한다.
- THEN: 원문은 user role에만 존재하고 system 메시지에는 재삽입되지 않는다.

**AC-04 · 모델 출력 후보 격리**
- GIVEN: 중복 역할 및 후보 term_id가 든 모델 출력이다.
- WHEN: 고정 검증 안내를 구성한다.
- THEN: system 안내에는 후보 role·term_id·raw output이 포함되지 않는다.

**AC-05 · 상태 계약 일치**
- GIVEN: v4 프롬프트 출력 상태를 schema enum과 비교한다.
- WHEN: 계약을 검사한다.
- THEN: 양쪽 모두 `select_terms`와 `needs_clarification`만 허용한다.

**AC-06 · 평가 출처 재현성**
- GIVEN: 30문항 평가 산출물이 제공된다.
- WHEN: PR에서 평가 결과를 검토한다.
- THEN: metadata의 commit이 실제 평가 대상 코드이고 working tree가 깨끗할 때만 PR head 검증 결과로 인정하며, 그렇지 않으면 기존 수치를 이전 dirty 실행으로 표시한다.
