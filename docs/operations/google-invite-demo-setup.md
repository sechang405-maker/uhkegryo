# Google 초대 데모 운영 전 체크리스트

> 상태: 코드 준비용 문서입니다. 현재 서비스는 `AUTH_MODE=local`이며 실제 Google OAuth, 운영 DB migration, 관리자 지정, 초대 코드 발급은 아직 수행하지 않습니다.

## 1. 먼저 결정할 값

- 테스트에 사용할 공개 HTTPS 도메인과 API 공개 origin
- 최초 관리자에 사용할 Google 계정 하나
- 각 초대 수혜자에게 지급할 누적 AI 요청 횟수와 운영자 전체 안전 예산
- 운영 OpenRouter 모델 및 계정별 한도와 별도로 적용할 전체 비용 차단선

## 2. Google Cloud 설정

1. Google Cloud에서 **웹 애플리케이션** 유형 OAuth 클라이언트를 준비합니다.
2. 동의 화면에는 로그인에 필요한 최소 범위인 `openid email profile`만 둡니다.
3. 승인된 redirect URI는 다음 규칙으로 정확히 등록합니다.

   ```text
   https://<API의 공개 origin>/api/auth/google/callback
   ```

   `GOOGLE_REDIRECT_URI` 값과 문자 단위로 같아야 합니다. 로컬 검증용 예시는 `http://localhost:8000/api/auth/google/callback`이며 운영에서는 HTTPS를 사용합니다.
4. 약 10명 제한 검증 중에는 별도 테스트 프로젝트와 테스트 사용자를 쓰는 방식을 우선 검토합니다. 공개 상태 전환·검증 필요 여부는 실제 동의 화면과 scope를 확정한 뒤 판단합니다.

공식 참고:

- [Google OAuth 2.0 Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect)
- [Google OAuth 정책](https://developers.google.com/identity/protocols/oauth2/policies)

## 3. 필요한 환경 변수

값이나 secret을 Git에 저장하지 않습니다.

```dotenv
AUTH_MODE=google_invite
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=https://<API 공개 origin>/api/auth/google/callback
AUTH_FRONTEND_ORIGIN=https://<프런트 공개 origin>
INVITE_CODE_PEPPER=<충분히 긴 무작위 비밀값>
INVITE_REDEEM_ATTEMPT_LIMIT=5
INVITE_REDEEM_WINDOW_SECONDS=900
ALLOWED_ORIGINS=https://<프런트 공개 origin>
DATABASE_URL=<운영 PostgreSQL URL>
```

`AUTH_FRONTEND_ORIGIN`은 경로가 없는 origin이어야 합니다. `GOOGLE_REDIRECT_URI`는 절대 URL이어야 하며, 운영 환경 쿠키는 HTTPS에서만 전송됩니다.

## 4. DB와 최초 관리자 준비

1. 운영 DB의 복구 가능한 백업을 먼저 만듭니다.
2. migration을 번호 순서대로 확인합니다: `009` 계정·쿼터 → `010` OIDC·세션·초대 코드 → `011` 관리자 메모 → `012` 계정 이전 요청 제약.
3. 격리 복원본에서 migration과 rollback 대신 백업 복구 절차를 검증합니다.
4. 최초 관리자는 이메일 문자열만으로 지정하지 않습니다. 실제 Google OIDC에서 검증된 issuer/subject를 확인한 뒤, 별도 승인된 일회성 bootstrap 절차로 `role=admin`을 부여해야 합니다.
5. bootstrap 이후 관리자 API에서 본인 역할을 확인하고, 자동 승격 경로가 없는지 확인합니다.

현재 저장소에는 운영 관리자 자동 지정 기능이 없습니다. 실제 연결 단계에서 bootstrap 방식과 최초 관리자 Google 계정을 사용자 확인 후 확정해야 합니다.

## 5. 초대 발급 전 검증

- 관리자 외 사용자의 관리자 API 접근이 403인지 확인
- 원문 초대 코드는 발급 응답에서 한 번만 보이고 DB·로그·목록에는 남지 않는지 확인
- 미사용 코드 폐기, 만료, 오입력 rate limit 확인
- 계정별 누적 한도·사용 완료·처리 중·잔여 표시 확인
- 성공한 AI 대화·개인 용어 초안만 1회 차감되는지 확인
- 실패·중복 제출·내부 재시도·고정 안내·이미지 재검색이 추가 차감되지 않는지 확인
- 잔여 1회에서 동시 요청 두 개 중 하나만 예약되는지 확인
- 차단 시 기존 세션이 폐기되는지 확인
- 계정 이전은 기존 계정으로 로그인한 상태에서 새 Google 로그인을 검증하고, 관리자 승인 후 기존 데이터·쿼터가 같은 `account_id`에 유지되는지 확인
- 이전 대상이 이미 다른 수혜자 계정에 연결된 경우 거부되는지 확인

## 6. 활성화 순서

1. 테스트 도메인과 Google OAuth 클라이언트 확정
2. 운영 DB 백업 및 migration 적용
3. 검증된 Google 신원으로 최초 관리자 bootstrap
4. `AUTH_MODE=google_invite` 및 환경 변수 적용
5. 관리자 1명으로 로그인·로그아웃·재로그인 검증
6. 테스트용 초대 코드 1개를 발급해 등록·차감·차단·복구 검증
7. 운영자 전체 비용 안전한도 확인 후 실제 초대 발급

각 단계 실패 시 다음 단계로 진행하지 않고, `AUTH_MODE=local`로 되돌리는 것만으로 DB schema가 되돌아가지는 않으므로 DB 복구는 사전 백업을 사용합니다.
