# Personal Remote Test Design

## Intent

배포 화면에서 저장소 소유자 본인의 기존 Codex 실행 경로가 연결될 수 있는지 나중에 제한적으로 검증할 수 있도록, 코드 경계와 모의 테스트만 준비한다. 이번 작업은 실제 OAuth, 터널, Vercel 설정, secret, Codex/API 호출을 만들거나 실행하지 않는다.

## Goals

- `personal_remote_test`를 기존 `standard`와 `anonymous_portfolio`에서 분리한다.
- Vercel 서버 프록시만 게이트웨이 secret을 읽고 브라우저에는 노출하지 않는다.
- 백엔드는 정확한 public origin/callback, gateway origin/Host, server secret, owner account ID, `active`, `admin`을 모두 검증한다.
- Google 로그인 시작과 콜백만 인증 예외로 두고, 미등록 또는 비소유자는 가입·초대 흐름 없이 거부한다.
- 세션 만료, 로그아웃, CSRF, Origin/Host 위조, 직접 터널 요청, 누락 설정, 공개 portfolio 연결을 fail closed로 검증한다.
- 기존 localhost Codex와 anonymous portfolio 동작을 변경하지 않는다.

## Non-goals and anti-goals

- main 변경, 원격 push/PR, Vercel 배포 또는 설정 변경
- 터널 설치/실행, secret 생성·등록·복사, OAuth 설정 변경
- 실제 API, Codex, PostgreSQL, Docker, Langfuse 호출 또는 서비스 재시작
- 개인 CLI를 자체 웹앱 백엔드로 사용하는 것이 공식적으로 보장된다고 주장하는 것

## Approaches considered

1. 기존 localhost 가드를 원격 Host까지 전역 확장: 경계가 섞이고 공개 portfolio가 Codex에 닿을 수 있어 제외한다.
2. anonymous portfolio 프록시에 조건을 추가: 익명 모드와 소유자 인증 모드가 결합되어 제외한다.
3. 별도 모드와 별도 정책/프록시(선택): 기존 기본값을 유지하고 새 모드에서만 다중 검증을 적용할 수 있다.

## Design

`Settings`는 `personal_remote_test`에서만 HTTPS public/gateway origin, 동일 public frontend/callback, 32자 이상 server secret, loopback PostgreSQL, 단일 worker, Codex Luna, Google auth, 정확한 owner ID를 요구한다. 값 하나라도 없거나 불일치하면 시작 단계에서 실패한다.

Vercel Route Handler는 브라우저의 Host 및 gateway-secret 헤더를 폐기하고 서버 환경의 고정 gateway origin/secret만 사용한다. 공개 origin이 아닌 요청, 허용되지 않은 경로, 잘못된 redirect는 전달하지 않는다. 쿠키는 HttpOnly/Secure/SameSite 속성을 유지하고 upstream redirect는 Google 로그인 시작 또는 정확한 public callback 귀환만 허용한다.

백엔드 gateway middleware는 모든 요청에서 gateway Host와 secret을 확인한다. 보호 API는 유효한 app session을 해석한 뒤 정확한 owner + active + admin만 허용한다. 로그인 시작/콜백만 세션 예외다. mutation은 정확한 Origin을 요구하며 기존 endpoint action 헤더도 계속 적용된다. 개인 모드에서는 auth의 start/callback/me/logout만 노출하고 admin/invite/transfer 조작 경로와 API 문서를 제외한다.

## Limitation

공식 문서에서 개인 Codex CLI를 자체 웹앱 백엔드로 사용하는 형태가 명확히 보장된다는 근거는 확인되지 않았다. 이 변경은 기술적 격리와 모의 검증 준비일 뿐 실제 사용 가능 범위나 약관 적합성을 결론내리지 않는다. 실제 OAuth, 터널, credentials, 배포 설정은 별도 승인과 공식 확인이 필요한 후속 단계다.
