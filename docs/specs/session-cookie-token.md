# 익명 세션 쿠키 토큰

## Why

익명 브라우저 세션을 식별할 때 쿠키 토큰 원문이 DB나 로그에 남지 않아야 한다. 토큰 발급과 쿠키 옵션을 API 경계에서 일관되게 사용한다.

## Goal

- 암호학적으로 안전한 무작위 세션 토큰을 발급한다.
- 저장소에 전달할 SHA-256 해시를 계산한다.
- 브라우저 쿠키를 `HttpOnly`, `SameSite=Lax`, `Path=/`, 달력 기준 3개월 만료로 설정한다.
- 개발 환경 HTTP에서만 `Secure=false`, 그 외에는 `Secure=true`로 설정한다.
- PostgreSQL 조회, 세션 만료·갱신, job 소유권 검증은 후속 세션 저장소 기능 범위다.

## What

1. 서버가 새 opaque token을 생성하고, 원문은 쿠키 설정에만 사용한다.
2. 서버는 같은 token의 SHA-256 hex digest를 반환해 호출자가 DB 저장을 요청할 수 있게 한다.
3. 응답은 달력 기준 3개월 만료 쿠키를 설정한다.
4. 기존 쿠키 토큰의 해시는 저장소에서 조회되어야 유효 세션으로 인정한다.

## How

- API: `create_session_token() -> str`, `hash_session_token(token: str) -> str`, `set_session_cookie(response, token, settings) -> None`.
- 토큰은 `secrets.token_urlsafe(32)`로 생성한다.
- 해시는 UTF-8 token의 SHA-256 lowercase hex digest다.
- 쿠키 이름은 `session_id`를 유지한다.
- 쿠키 옵션: `httponly=true`, `samesite="lax"`, `path="/"`, `max_age=session_cookie_max_age()`, `secure=(environment != "development")`.
- 토큰 원문과 digest 모두 로그에 쓰지 않는다.

## AC

- **Given** token 발급 요청, **When** `create_session_token()`을 호출, **Then** 매번 예측 불가능한 비어 있지 않은 token을 반환한다.
- **Given** 같은 token, **When** SHA-256을 계산, **Then** 같은 lowercase hex digest를 반환한다.
- **Given** development 환경, **When** 응답 쿠키를 설정, **Then** `session_id` 쿠키는 HttpOnly·SameSite=Lax·Path=/·달력 기준 3개월이며 Secure는 false다.
- **Given** production 환경, **When** 응답 쿠키를 설정, **Then** 같은 정책에 Secure=true다.
- **Given** 요청에 token 쿠키가 있지만 세션 저장소에 일치하는 digest가 없다, **When** 인증 의존성이 실행, **Then** 인증 실패를 반환한다. (후속 저장소 작업의 계약)
