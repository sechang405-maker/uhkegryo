# Langfuse 연결 대상 전환

## Why
팀은 발표까지 공용 trace를 보고, 발표 이후 각자 로컬에서 포트폴리오를 재현한다. 코드 수정 없이 주소와 프로젝트 키를 바꾸는 것으로 전환 가능해야 한다.

## Goal
동일 트레이싱 코드로 로컬 및 공용 서버에 전송한다. Out of Scope: 자동 날짜 전환, trace 데이터 자동 이전, 백엔드 전체 배포.

## What
공용 사용 시 LANGFUSE_APP_URL과 공용 프로젝트 키를 설정한다. 로컬 전환 시 이 URL 설정을 제거하고 로컬 프로젝트 키를 설정한 뒤 API를 재생성한다. 키 누락 시 기존 비활성화 동작을 유지한다. 서버 장애 시 임의로 다른 서버에 전송하지 않는다.

## How
Compose api의 LANGFUSE_HOST와 LANGFUSE_BASE_URL은 LANGFUSE_APP_URL을 동일하게 사용한다. 기본 주소는 http://langfuse-web:3000이다. 직접 실행하는 Python Settings는 LANGFUSE_BASE_URL을 LANGFUSE_HOST보다 우선하며 기본값은 http://localhost:3000이다. 전환 시 SDK를 다시 초기화하도록 프로세스를 재시작한다. 키는 .env 또는 Secret Manager에만 둔다.

## AC
- GIVEN URL override 없음 WHEN Compose 렌더링 THEN api의 두 주소가 로컬 내부 주소다.
- GIVEN 공용 URL WHEN Compose 렌더링 THEN api의 두 주소가 동일 공용 URL이다.
- GIVEN 두 환경변수 WHEN Settings 생성 THEN BASE_URL을 우선한다.
- GIVEN HOST만 설정 WHEN Settings 생성 THEN HOST를 사용한다.
- GIVEN 로컬/공용 프로젝트 WHEN 각 대상에서 job 실행 THEN 해당 대상 UI에 trace가 나타난다. 실제 수신은 배포 후 별도 확인한다.
