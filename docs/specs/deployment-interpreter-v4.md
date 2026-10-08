# 배포 해석 모델·프롬프트 v4 정렬

## Why
이전 작업 트리에서 평가한 GPT-4.1-mini·v4를 배포 후보 설정으로 선택한다. 같은 v4 이름이어도 현재 파일의 지문이 달라 과거 40/40을 현재 PR의 품질 통과 근거로 사용할 수 없다. 측정 지표는 배포·로컬 실행 설정의 모델/경로/버전 세 값 일치다.

## Goal
Cloud Build API와 Compose API, 환경 변수 예시를 openai/gpt-4.1-mini·v4로 정렬한다. 제외: 실제 클라우드 배포, 기본 Settings의 구버전 호환 변경, 원격 Prompt 운영 구현, 외부 평가 실행.

## What
과거 40/40·비용·지연은 이전 작업 트리의 참고 결과로 제한한다. 현재 PR의 실제 모델 품질·운영 배포·외부 연결은 재검증 전 미검증이다.

새 Compose API는 v4 파일과 v4 버전을 함께 기본 적용한다. 명시적 환경 변수 override는 경로·버전을 모두 설정한 경우 유지한다. 두 값이 미설정 또는 빈 값이면 기본 v4를 사용한다. 한 값만 설정하면 API 시작 명령에서 uvicorn 실행 전에 오류로 중단한다. Cloud Build API는 같은 모델과 이미지 내부 v4 경로·버전을 명시한다. MCP에는 해석 설정을 새로 추가하지 않는다.

API 재배포 시 서비스에 별도 설정된 LANGFUSE_HOST와 배포 목록 밖 환경변수를 보존한다.

## How
- Dockerfile에 v4 파일을 이미지 내부 경로로 복사한다.
- LLM_MODEL=openai/gpt-4.1-mini
- INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4
- Cloud Build: INTERPRETER_PROMPT_PATH=/app/prompts/uhkegryo-interpreter-v4.md
- Compose: 같은 이미지 내부 경로를 기본으로 하며 명시적 override 허용. 원본 값은 COMPOSE_PROMPT_PATH/COMPOSE_PROMPT_VERSION으로 전달하고 Python 시작 명령에서 설정 여부를 비교한다. 중첩 required 치환식은 사용하지 않는다.
- 직접 Python 실행 예시: ./prompts/uhkegryo-interpreter-v4.md
- 파일의 Prompt 이름 선언이 있으면 설정 버전과 일치해야 하며, 불일치는 adapter 초기화 오류다. 사용자 지정 파일은 파일명으로 제한하지 않는다.
- 경로와 버전을 함께 설정해야 v4 검증 피드백 분기가 적용된다. 배포 가이드·README는 이 계약을 따른다.

- Preview 출력 계약과 2048 토큰 상한은 [interpreter-catalog-output-repair.md](interpreter-catalog-output-repair.md)를 따른다.
- Cloud Build deploy-api는 --update-env-vars로 지정된 값만 갱신한다. --set-env-vars/--clear-env-vars/--remove-env-vars는 사용하지 않는다. MCP 배포는 이번 수정 범위 밖이다.

## AC
- Given 기존 API 서비스에 LANGFUSE_HOST 설정, When Cloud Build API 재배포, Then 지정된 환경변수만 갱신하고 LANGFUSE_HOST를 삭제하거나 덮어쓰지 않는다. 회귀 검증은 실제 deploy-api 명령의 비파괴 갱신 옵션과 삭제 옵션 부재를 검사한다.
- Given 과거 실행과 현재 파일 지문 불일치, When 모델 선택 근거를 기록, Then 과거 결과는 참고로만 사용하고 현재 PR의 품질 통과로 주장하지 않는다.
- Given 새 배포 구성, When Cloud Build API 환경 변수 확인, Then 모델·v4 경로·v4 버전이 모두 명시된다.
- Given 기존 v0 경로만 지정한 .env 또는 버전만 지정한 환경, When API 시작 명령 실행, Then 두 값을 설정하라는 오류로 중단하고 uvicorn을 실행하지 않는다.
- Given 파일의 Prompt 이름과 설정 버전 불일치, When adapter 초기화, Then 모델 호출 전에 오류로 중단한다.
- Given 두 값이 빈 값 또는 미설정, When Compose 렌더링 및 API 시작 명령 실행, Then 기본 v4를 적용하고 uvicorn을 실행한다.
- Given 명시적 v0/v0 또는 v4/v4, When API 시작 명령 실행, Then 지정한 값을 유지하고 uvicorn을 실행한다.
- Given override 없음, When Compose API 설정 확인, Then 같은 세 값이 기본 적용된다.
- Given 환경 변수 예시, When Settings와 adapter를 로드, Then 모델은 GPT-4.1-mini, 버전은 v4이고 실제 v4 파일이 파싱된다.
- Given 기존 adapter/worker 회귀 테스트, When 실행, Then 이전 버전의 명시적 설정과 v4 동작이 유지된다.

검증(2026-10-04): backend 497 passed / 28 skipped (LLM_MODEL=openai/gpt-4o-mini, LANGFUSE_TRACING_ENABLED=false); Docker Compose CLI 렌더링과 API 시작 명령 검사로 기본 v4·빈 값/미설정·명시적 v0/v4·불완전한 설정 차단 확인. 실제 이미지 빌드·배포·외부 품질 평가는 미검증이다.

재배포 환경변수 보존 보완(2026-10-04): backend 498 passed / 28 skipped. deploy-api 비파괴 갱신 옵션과 LANGFUSE_HOST 덮어쓰기/삭제 부재 회귀 검증 통과. 실제 Cloud Run 재배포는 수행하지 않았으며 유지 동작은 공식 CLI 계약과 명령 검증 기준이다. 근거: https://docs.cloud.google.com/run/docs/configuring/services/environment-variables#update
