# 개인 로컬 Codex Luna 실행

이 실행 모드는 본인 Windows PC 전용이다. 밀리테크의 공식 `codex exec` 패턴을 적용하며 모델은 **`gpt-5.6-luna`**, reasoning effort는 `low`다. 다른 모델·OpenRouter·API 키 과금 경로로 자동 전환하지 않는다. 기존 `NEXT_PUBLIC_UI_DEMO=1` 독립 데모와 기본 OpenRouter 실행은 유지된다.

## 로그인과 사용량

- 이미 로그인된 Codex 데스크톱 설치가 필요하다. `login status`에서 ChatGPT 로그인이 확인되어야 한다. 앱은 로그인·OAuth 승인·토큰 발급을 수행하지 않는다.
- 기본 설치 위치 `%LOCALAPPDATA%/OpenAI/Codex/bin`의 가장 최근 버전 `codex.exe`를 찾아 OpenAI Authenticode 서명을 검증한다. 다른 설치가 필요하면 `CODEX_BIN_DIR` 또는 `CODEX_EXECUTABLE` 중 하나만 지정한다. 전역 PATH와 서명 설정은 바꾸지 않는다.
- **로컬 UI여도 추론은 OpenAI 서비스에서 처리된다.** 사용자가 입력한 설명, 검수 카탈로그, 답변에 필요한 제한된 대화 문맥과 회상 원문이 기존 Codex 로그인으로 전송된다. API 키·DB URL·프로세스 비밀 환경변수는 자식 프로세스에 전달하지 않는다.
- Codex 구독 사용량/한도를 소비한다. 무료·무제한을 보장하지 않는다. 로그인 만료·한도·모델 접근 오류는 실패 안내로 반환하며 유료 API로 우회하지 않는다.
- CLI는 `--ignore-user-config --ephemeral --sandbox read-only`로 실행한다. 외부 도구·웹 검색·앱·MCP·플러그인·셸을 끈다. 인증은 CLI가 직접 처리하며 앱이 인증 파일을 읽거나 복사하지 않는다.

## 실행 경계

API와 Codex는 로그인된 Windows **호스트**에서 실행한다. Codex 인증 폴더를 Docker에 마운트하지 않는다. 기존 팀용 `docker-compose.yml` 대신 별도 `compose.local-codex.yml`에는 로컬 PostgreSQL 하나만 정의했다. 이 문서 추가 시 DB 생성·마이그레이션·데이터 삭제는 실행하지 않았다.

이미 별도 개인 로컬 PostgreSQL을 쓰고 있다면 그대로 사용한다. 새 DB가 필요한 경우에만 본인이 비밀번호를 정하고 `LOCAL_POSTGRES_PASSWORD`를 현재 터미널에 설정한 뒤 실행한다. 비밀번호를 채팅이나 Git에 넣지 않는다.

```powershell
docker compose -f compose.local-codex.yml up -d db
```

API 터미널에서 `DATABASE_URL`을 해당 개인 로컬 DB 연결 문자열로 설정한다. 예시 구조는 `postgresql://uhkegryo:<URL-encoded-password>@127.0.0.1:55432/uhkegryo`다. 실제 비밀번호는 본인이 입력하며 로그에 출력하지 않는다. 원격 주소와 `?host=...` 같은 query override는 거부한다. 기존 팀 `.env`를 로드하지 않는다.

저장소 루트에서 Python 3.11 이상으로 가상환경을 준비하고 기존 requirements를 설치한다. 새 DB 초기화는 아래 명령으로 **명시적으로** 수행한다. 기존 데이터가 있는 DB는 연결 대상을 확인한 뒤 실행한다. 초기화는 기존 migration 이력을 따르며 drop/delete 명령이 아니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m backend.local_codex --init-db
.\.venv\Scripts\python.exe -m backend.local_codex
```

API는 `127.0.0.1:8000`, worker는 1개다. `--reload`, 여러 API 프로세스, 외부 bind, 터널·포트포워딩을 사용하지 않는다. Host/Origin/peer도 loopback만 허용한다. 이것은 로그인 기능이 아니므로 같은 PC의 다른 프로그램까지 격리하지는 않는다.

별도 프런트 터미널:

```powershell
cd frontend
npm ci
$env:NEXT_PUBLIC_UI_DEMO = '0'
$env:AGENT_API_ORIGIN = 'http://127.0.0.1:8000'
npm run build
npm run start -- -p 3100 -H 127.0.0.1
```

브라우저에서 `http://127.0.0.1:3100`을 연다. 데모 빌드를 실행 중이었다면 반드시 다시 빌드한다. 로컬 Codex API는 이미지 검색/MCP/Langfuse를 연결하지 않으며 검색 미연결 상태를 표시한다. 답변·용어와 기존 세션/회상 흐름만 사용한다. 이미지 검색을 원하면 별도 로컬 검색 구성과 외부 전송 범위를 결정해야 한다.

## 실패, 취소, 재시도, 데이터

### 이 PC에 구성한 전용 DB 다시 실행하기

사용자 승인으로 생성한 전용 비밀번호와 연결값은 저장소 루트 `.env.local-codex`에만 있다. 기존 `.gitignore`의 `.env.*` 규칙으로 제외된다. 파일은 평문이므로 읽을 수 있는 로컬 사용자는 DB에 접근할 수 있다. 내용을 채팅·로그·Git에 복사하지 않는다. `--local-settings`를 지정할 때만 이 파일에서 DB 연결값을 읽으며, 다른 설정이나 팀 `.env`는 읽지 않는다. 비밀번호를 새로 생성하여 기존 파일을 덮어쓰지 않는다.

Docker Desktop 엔진 실행 후 저장소 루트에서:

```powershell
docker compose --env-file .env.local-codex -f compose.local-codex.yml up -d db
python -m backend.local_codex --local-settings
```

Python 의존성이 설치된 가상환경에서 실행한다. 이 PC의 새 DB에는 migration 001~005를 이미 적용했다. 향후 migration을 명시적으로 적용할 때만 `python -m backend.local_codex --local-settings --init-db`를 사용한다. 프런트는 위의 live 빌드/3100 포트 명령으로 실행한다.

종료는 API와 프런트 터미널에서 각각 `Ctrl+C`, DB는 다음 명령을 사용한다. 다른 프로젝트나 Docker 엔진 전체를 정지하지 않는다.

```powershell
docker compose --env-file .env.local-codex -f compose.local-codex.yml stop db
```

`down -v`, volume 제거, DB 초기화/삭제 명령은 실행하지 않는다. 볼륨 `uhkegryo-local-codex_uhkegryo_codex_data`에 앱 DB `uhkegryo`와 합성 테스트 전용 `uhkegryo_test`를 분리했다. 기존 개인/팀 DB는 사용하지 않았다.

2026-10-14 검증: 새 테스트 DB에서 backend **683 passed, 0 skipped, 0 failed**, 프런트 live production build 통과. 실제 브라우저에서 합성 세션 2개와 각 요청·답변을 저장하고 세션 전환을 확인했다. 전용 DB·API·프런트를 재시작한 뒤 동일 job ID, 완료 상태, 요청, 답변이 복원됐다. 합성 응답은 테스트 프로세스에서만 사용했고 최종 API는 실제 Codex Luna 모드로 다시 실행했다. 추가 실제 모델 호출은 0회이며 앞선 합성 호출 1회 성공을 재사용했다.

저장 범위는 세션 소유권/목록, 요청 원문, job 상태·결과(답변·선정 용어), 제한된 대화 문맥이다. 아래 개인 로컬 프로필을 사용하면 쿠키가 없어져도 같은 PC의 기록을 복원한다. 합성 검증 세션 2개는 삭제하지 않고 남겨 두었다. 백업/복구 정책은 별도 결정 사항이다.

- 단일 CLI 실행 제한은 adapter당 1개이며 launcher는 단일 API worker만 실행한다. 큐 대기도 `CODEX_TIMEOUT_SECONDS`(기본 180초, 10~300초)에 포함된다.
- CLI timeout, API 종료 또는 job lease 취소 시 해당 자식 프로세스 트리를 종료하고 임시 응답 파일을 정리한다. 브라우저 창을 닫는 것은 job 취소가 아니다; 기존 job은 종료 상태까지 실행될 수 있다.
- adapter는 재호출하지 않는다. timeout/잘못된 구조화 출력은 기존 job 정책(최대 3 attempts)으로 재시도할 수 있어 사용량이 추가될 수 있다. 로그인·CLI 실패·모델 불일치는 자동 재시도하지 않는다.
- interpretation 및 recall은 기존 Pydantic 계약과 원문 근거 검증을 유지한다. CLI stdout은 버리고 stderr는 제한된 헤더만 내부 판별하며 원문을 로그로 남기지 않는다.
- 일반 실행 모드의 기존 3개월 만료는 유지한다. 개인 로컬 프로필의 대화는 직접 삭제할 때까지 보관한다. 자동 삭제·주기 작업은 없다. Compose volume 제거 명령을 실행하지 않는다.

## 개인 대화 보관과 직접 삭제

먼저 처리 중인 요청이 없는지 확인하고 API를 종료한 뒤 `python -m backend.local_codex --local-settings --init-db`로 migration 006을 적용한다. 기존 기록은 삭제하지 않고 `retained` 플래그만 추가한다. 이어 같은 launcher로 API를 실행하고 live 프런트를 새로 빌드한다.

`--local-settings` 실행은 Git에서 제외된 `.env.local-profile`을 최초 한 번 생성하여 개인 로컬 소유권을 유지한다. 파일을 덮어쓰거나 Git·로그에 복사하지 않는다. 이 모드는 한 사람이 사용하는 전용 로컬 DB에만 사용한다. 화면의 프로필 초기화 요청은 이 전용 DB의 기존 대화를 개인 프로필로 채택하고 만료 없이 보관한다. 이전 브라우저 쿠키의 소유권은 유지하지 않는다. 쿠키 삭제·만료나 API 재시작 후에도 같은 파일과 DB로 복원할 수 있다. 여러 사용자/팀 DB에 이 모드를 연결하지 않는다.

세션 목록의 **삭제** 버튼은 영구 삭제 확인창을 연다. 확인하면 해당 세션의 요청·답변·참고 링크·대화 문맥과 job 기록을 함께 삭제한다. 다른 대화와 외부 Pinterest 원본은 삭제하지 않는다. 취소나 실패 시 기록은 유지하며, 처리 중인 job이 있으면 완료 후 삭제하도록 409로 거절한다. 중복 삭제 요청은 안전하게 204를 반환한다. 삭제 후 되돌리기는 제공하지 않으며 자동 삭제 스케줄도 만들지 않는다.

DELETE `/api/sessions/{id}`는 기존 쿠키 소유권과 `X-Conversation-Action: delete`, Origin을 검사한다. 로컬 프로필 초기화 POST `/api/local/profile`은 Codex 로컬 설정과 loopback 경계를 추가로 검사한다. 일반 모드의 소유권 검사와 만료 정책은 유지된다.

## 검증

`python -m pytest backend/tests/test_codex_local.py`는 실제 Codex 호출 없이 mock과 로컬 자식 프로세스로 경계를 검증한다. 전체 backend/frontend 회귀와 합성 입력 실제 호출 1건의 결과는 작업 완료 보고서에 구분해 기록한다. 실제 모델 품질은 합성 1건만으로 일반화하지 않는다.

2026-10-14 로컬 검증: backend 650 passed/31 skipped, frontend 72 passed. 합성 입력 1건이 CLI 실측 `gpt-5.6-luna`/`openai`로 한국어 답변을 생성했고 Pydantic 및 카탈로그 resolver를 통과했다. 실제 DB 통합·Compose 생성·마이그레이션·이미지 검색은 실행하지 않았다. 독립 검토에서 발견한 검색 성공 오표시를 수정했고 최종 차단 결함은 없었다.

참고 구현: [밀리테크 analyze.py](https://github.com/sechang405-maker/militech/blob/master/militech/analyze.py), [runtime.py](https://github.com/sechang405-maker/militech/blob/master/militech/runtime.py). 밀리테크 자체는 변경하지 않았다.
