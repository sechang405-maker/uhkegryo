# Anonymous Portfolio Demo Design

## 목적과 경계

강사가 임시 HTTPS 링크로 로그인 없이 실제 AI 해석, 대화 이력, 이미지 검색, 개인 용어 생성을 시험할 수 있는 별도 로컬 실행 환경을 만든다. 기존 Google 초대/관리자 기능, owner-only Codex Luna 환경, 개인 PostgreSQL 볼륨과 비밀 파일은 변경하거나 참조하지 않는다. 이번 구현은 로컬 준비와 mock 검증까지만 포함하며 OpenRouter 키 생성·등록·탐색, 실제 모델 호출, 터널 설치·실행, 외부 공개는 포함하지 않는다.

## 실행 구조

`compose.portfolio.yml`은 고정 프로젝트 이름 `uhkegryo-portfolio`와 별도 PostgreSQL volume을 사용한다. DB, API, SearXNG는 Compose 내부망에만 두고 frontend만 `127.0.0.1`에 게시한다. 모든 서비스는 `restart: "no"`이며 명시적 start/stop 스크립트로만 실행한다. 추후 Quick Tunnel은 frontend loopback 포트만 대상으로 하며 API·DB 포트를 직접 공개하지 않는다.

API에는 `RUNTIME_MODE=anonymous_portfolio`를 추가한다. 이 모드에서는 Google auth, admin demo, local Codex profile, API 문서가 노출되지 않는다. 익명 브라우저별 암호학적 세션 토큰과 owner-scoped DB 조회는 유지하며, 변경 요청은 정확한 Origin과 action header를 함께 검증한다. 미정인 공개 origin, 평가 종료 시각, 무료 모델 선택은 안전한 시작 차단 입력으로 둔다.

## 무료 모델과 호출 예산

포트폴리오 모드는 `LLM_BACKEND=openrouter`, 공식 OpenRouter base URL, 서버 전용 API key만 허용한다. 모델은 코드가 승인한 정확한 allowlist 항목이어야 하며 `:free` variant 또는 명시적으로 승인한 무료 router만 허용한다. paid model, 임의 모델 배열, 유료 fallback, Codex fallback은 거부한다. 실제 모델 선택과 품질 검증은 키 사용 승인 뒤에 한다.

외부 LLM HTTP 호출 직전에 PostgreSQL에서 UTC 일자별 counter를 원자적으로 예약한다. 대화 해석, recall/routing 같은 추가 모델 단계, 내부 재시도, 개인 용어 제안을 모두 같은 40회 한도에 포함한다. 40회를 사용하면 추가 호출은 네트워크 전송 전에 중단한다. 이 카운터는 session/job 수와 별도이며 동시 AI worker는 1개로 고정한다. 402·403·429와 무료 모델 부재는 유료 전환 없이 실패한다.

## 검색과 데이터 흐름

기존 검색 품질 경로를 보존한다. 검수된 카드의 `query_fragments`만 SearXNG/Pinterest 검색에 보내며 사용자 원문과 OpenRouter 비밀은 보내지 않는다. LLM에는 사용자 질문, 필요한 대화 문맥, 활성 카드 후보만 전송된다. Langfuse는 포트폴리오 모드에서 금지하고 질문·비밀을 application log에 기록하지 않는다. 대화 원문은 기능상 별도 portfolio DB에 저장하지만 자동 영구 삭제 정책은 사용자 승인 전 활성화하지 않는다.

## 운영과 검증

start 스크립트는 공개 origin, 평가 종료 시각, 무료 모델 allowlist와 key 존재를 값 출력 없이 점검하고 내부 health가 준비된 뒤에만 터널 실행 준비 상태를 보고한다. 현재 터널 명령은 문서화만 하고 실행하지 않는다. stop 스크립트는 portfolio 프로젝트만 내리며 volume 삭제는 하지 않는다.

mock 테스트는 설정 fail-closed, 40회 원자적 호출 예약, 다른 익명 owner 데이터 차단, auth/admin/docs/local-Codex 차단, 기존 개인 모드 회귀, Compose 포트·restart·project/volume 격리를 검증한다. 실제 모델 품질·지연과 터널 HTTPS/cookie 동작은 키와 외부 공개 승인을 받은 뒤 별도 검증한다.
