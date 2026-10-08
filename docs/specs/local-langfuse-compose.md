# Local Langfuse Compose

## Why

로컬 개발자가 Docker Compose로 Langfuse 인프라를 준비하고 기동 상태를 확인할 수 있어야 한다.

## Goal

- Compose로 애플리케이션과 로컬 Langfuse 인프라를 실행한다.
- Langfuse UI는 `http://localhost:3000`에서 연다.
- Langfuse 저장 서비스는 앱의 Neon `DATABASE_URL`과 분리한다.
- 이 Spec은 Langfuse 인프라 준비만 다룬다. 애플리케이션 LLM 관측 데이터가 UI에 나타나는 것은 완료 조건이 아니다.
- Out of Scope: worker root trace 생성·lifecycle 연결, 운영 배포, 원격 Prompt·Dataset 설정. Worker trace lifecycle 구현은 [관측 Spec](./observability-and-prompt-versioning.md)을 기준으로 별도 PR에서 다룬다.

## What

- Langfuse web·worker와 구동에 필요한 PostgreSQL, ClickHouse, Redis, MinIO만 로컬 서비스로 실행한다.
- Langfuse 데이터는 named volume에 보관한다.
- 애플리케이션 API는 기본적으로 Compose 내부 주소 `http://langfuse-web:3000`을 사용한다. `LANGFUSE_APP_URL` 설정 시 두 주소 모두 지정한 공용 주소를 사용한다. 전환 계약은 [연결 대상 전환](./langfuse-target-switching.md)을 따른다.

## How

- Langfuse v4 공식 컨테이너 이미지와 해당 버전의 필수 저장 서비스만 사용한다.
- Langfuse 앱의 내부 인증값은 `.env.example`에 명시하고 `.env`에서 제공한다.
- 호스트에 공개하는 Langfuse UI는 `127.0.0.1:3000`으로 제한한다. MinIO는 로컬 브라우저 업로드 URL인 `127.0.0.1:9090`만 공개한다.
- API Dockerfile은 기존 requirements에서 이미 Langfuse SDK를 설치하므로 변경하지 않는다.

## AC

- GIVEN: Docker Compose와 필수 `.env` 값이 준비되어 있다. WHEN: `docker compose config --quiet`를 실행한다. THEN: 구성 검증이 통과한다.
- GIVEN: Compose 서비스가 정상 기동했다. WHEN: 호스트에서 `http://localhost:3000`을 연다. THEN: Langfuse UI가 표시된다.
- GIVEN: Compose 서비스가 정상 기동했다. WHEN: web `http://localhost:3000/api/public/health`와 `docker compose exec -T langfuse-worker sh -c 'wget -S -O- "http://$(hostname -i):3030/api/health"'`를 실행한다. THEN: 두 endpoint가 HTTP 200을 반환하고 worker는 `{"status":"ok"}`를 응답한다.
- GIVEN: `LANGFUSE_APP_URL` 미설정이고 Compose의 API 서비스가 실행 중이다. WHEN: API가 `LANGFUSE_BASE_URL`과 `LANGFUSE_HOST`를 읽는다. THEN: 두 값 모두 `http://langfuse-web:3000`이고 Langfuse SDK가 이 주소에 연결한다.
- GIVEN: `docker compose down`으로 서비스를 중지한다. WHEN: named volume을 확인한다. THEN: Langfuse 저장 데이터가 유지된다.
