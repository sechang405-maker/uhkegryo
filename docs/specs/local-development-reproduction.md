# 로컬 개발 재현 절차

## Why

- **페르소나**: 저장소를 처음 clone한 팀원 또는 평가자.
- **상황**: FastAPI, 외부 Neon PostgreSQL, 로컬 Langfuse Compose, 별도 Next.js 개발 서버가 함께 필요하다.
- **문제**: 기존 README는 API Compose 실행만 안내해 DB migration, frontend 실행, Langfuse와 충돌하지 않는 frontend 포트를 알 수 없었다.
- **측정 지표**: 새 개발자가 README만으로 현재 구현 범위의 API health와 frontend 입력·polling 화면까지 시작하는 데 필요한 명령·기대 결과가 빠지지 않는다.

## Goal

- README가 현재 구현된 범위의 로컬 시작 절차를 PowerShell 기준으로 제공한다.
- 절차는 `.env` 준비, Compose 기동, 명시적 migration, `/health` 확인, frontend 실행, 종료를 모두 포함한다.
- API가 8000, Langfuse UI가 3000을 사용하므로 frontend 개발 서버는 3001에서 시작한다.

**Out of Scope**: Neon 계정·DB 자동 생성, 실제 비밀값 배포, 앱 startup migration 자동화, frontend Docker 이미지, Pinterest·OpenRouter·Langfuse의 실제 외부 호출 성공 보장, 결과 UI 구현.

## What

### Happy Path

1. 사용자가 저장소를 clone하고 `.env.example`을 `.env`로 복사한다.
2. 사용자가 Neon 개발 DB URL, OpenRouter key, Langfuse 내부 비밀값, SearXNG `SEARXNG_SECRET`을 자신의 `.env`에 입력한다.
3. `docker compose up --build -d`로 API, SearXNG, Langfuse 저장 서비스를 시작한다.
4. 사용자가 API 컨테이너에서 migration runner를 명시적으로 실행한다. 앱 startup은 migration을 자동 실행하지 않는다.
5. `GET /health`가 `{"status":"ok"}`를 반환하는지 확인한다.
6. 별도 PowerShell에서 Node.js 20.9 이상으로 frontend 의존성을 설치하고 3001 포트에서 Next.js를 실행한다.
7. 브라우저에서 입력·제출·job polling 화면을 확인하고, 종료 시 Compose와 frontend 개발 서버를 중지한다.

### Edge Cases

| 상황 | 처리 방식 |
| --- | --- |
| `.env`의 Neon URL·OpenRouter key가 비어 있음 | Compose 기동 또는 실제 Agent job이 실패할 수 있음을 명시하고, 값을 저장소에 넣지 않는다. |
| migration 실행 실패 | job을 제출하지 말고 `DATABASE_URL`과 migration 오류를 확인한다. migration을 startup에서 자동 재시도하지 않는다. |
| frontend가 기본 3000 포트로 시작됨 | Langfuse UI와 충돌하므로 `--port 3001`을 사용한다. |
| Pinterest·OpenRouter·Langfuse 외부 호출 실패 | `/health` 성공과 Agent 결과 생성은 별개로 기록한다. 비밀값이나 응답 원문을 문서에 남기지 않는다. |
| 결과 UI가 아직 병합되지 않음 | README는 입력·polling 화면까지만 현재 범위로 표시하고, 용어·Pin 결과를 보았다고 주장하지 않는다. |

## How

- 수정 범위는 `README.md`와 이 Spec으로 한정한다.
- backend와 SearXNG는 Docker Compose에서 실행하고, frontend는 호스트의 Node.js 개발 서버에서 실행한다.
- migration은 API 컨테이너의 `asyncpg`, `backend.db.migrate.migrate`, `.env`의 `DATABASE_URL`을 이용해 한 번 명시적으로 실행한다.
- README에는 실제 key·token·DB URL을 기록하지 않고 변수명과 준비 책임만 기록한다.
- `GET /health`는 API liveness 확인이다. DB·LLM·Pinterest·Langfuse trace 성공을 보장하는 readiness 또는 E2E 검사는 아니다.

## AC (Given-When-Then)

**AC-01 · 필수 준비 정보**
- GIVEN: 저장소를 새로 clone한 개발자
- WHEN: README의 사전 준비를 읽는다
- THEN: Docker Compose, Node.js 20.9 이상, Neon 개발 DB URL, OpenRouter key, Langfuse 내부 비밀값, SearXNG `SEARXNG_SECRET`이 필요함을 알 수 있다.

**AC-02 · 명시적 migration과 health**
- GIVEN: `.env`를 채우고 Compose API를 기동했다
- WHEN: README의 migration 명령과 `/health` 확인 명령을 실행한다
- THEN: migration 자동 실행을 가정하지 않으며 health의 기대 JSON을 확인할 수 있다.

**AC-03 · frontend 포트**
- GIVEN: Langfuse UI가 localhost 3000을 사용한다
- WHEN: README의 frontend 시작 명령을 실행한다
- THEN: Next.js가 3001에서 실행되어 포트 충돌이 없다.

**AC-04 · 현재 범위의 정직한 표시**
- GIVEN: frontend 결과 UI가 main에 아직 없다
- WHEN: README의 확인 범위를 읽는다
- THEN: 입력·제출·polling과 결과 표시를 혼동하거나 전체 E2E 성공을 주장하지 않는다.
