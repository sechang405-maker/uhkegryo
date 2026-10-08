# 공용 Langfuse와 발표 후 로컬 전환

공용 연결과 로컬 연결은 같은 트레이싱 코드를 사용한다. 장애 시 자동 fallback이나 날짜 기반 자동 전환은 없다. 데이터는 각 서버에 별개로 저장된다.

## 공용 서버 생성과 팀 접속

PowerShell에서 `./scripts/deploy-langfuse.ps1`을 실행한다. 기존 `.env`의 필수 Compose 값이 필요하다. 기본 프로젝트는 proj2-509406, VM은 langfuse-shared, zone은 us-central1-a다. 기존 VM이나 비밀값 파일이 있으면 재생성을 거부하므로 실패 시 생성된 리소스를 먼저 확인한다.

HTTPS 주소와 로그인 이메일/비밀번호, 프로젝트 API 키는 `.env.langfuse-gcp`에 저장된다. 관리자 비밀번호와 secret key는 Git/메신저에 공유하지 않는다. 각 팀원은 공용 서버에 자신의 계정을 생성하고 관리자에게 조직 초대를 받는다. SMTP가 없으면 초대 이메일이 발송되지 않으므로 UI의 초대 링크를 직접 전달한다. 팀 계정 생성 후 필요하면 AUTH_DISABLE_SIGNUP=true로 추가 가입을 막는다(새 초대 계정 가입도 막힘).

## 공용 서버로 전환

```powershell
./scripts/set-langfuse-target.ps1 -Target shared
docker compose up -d --build --no-deps api
```

첫 전환 때 로컬 키를 `.env.langfuse-local`에 보관한다. 공용으로 설정한 `.env`를 팀에 공유하지 않고, 팀원은 자신의 로컬 키를 백업하고 공용 프로젝트 키를 안전하게 설정한다. 공용 주소는 LANGFUSE_APP_URL에 넣으며 Compose는 HOST와 BASE_URL을 같은 값으로 전달한다. 직접 Python 실행은 HOST와 BASE_URL도 같은 공용 주소를 사용한다.

SDK가 설치된 Python에서 `py scripts/verify-langfuse.py .env.langfuse-gcp`와 `py scripts/verify-langfuse.py .env.langfuse-local`로 양쪽 수신을 확인한다. 이 검사는 LLM 호출 없이 합성 worker span을 보내고 v4 Observations API에서 조회한다. 기존 로컬 조직/초대는 공용 서버로 이전되지 않으므로 팀원을 공용 조직에 다시 초대한다.

향후 Cloud Run api를 배포할 때도 LANGFUSE_HOST와 LANGFUSE_BASE_URL을 공용 HTTPS 주소로 설정하고, 공용 프로젝트 키를 Secret Manager에서 주입한다. 현재 Cloud Run mcp와 신규 api 배포는 이 작업 범위에 포함되지 않는다.

## 비용과 시작/정지

VM은 매번 시작 후 4시간에 자동 정지한다. 정지 중에는 UI/trace 수신 모두 불가능하고 SDK 전송 실패가 발생할 수 있다. 항상 전송해야 할 때만 자동 정지 정책을 바꾼다. 수신 확인 후 수동 정지하려면:

```powershell
gcloud compute instances stop langfuse-shared --zone=us-central1-a --project=proj2-509406
gcloud compute instances start langfuse-shared --zone=us-central1-a --project=proj2-509406
```

VM CPU/메모리는 실행 시간, 디스크는 할당 용량, 고정 IP는 유지 시간, 추가 네트워크/백업은 사용량에 따라 과금된다. 무료 크레딧 잔액/만료일은 Billing에서 확인한다. 예산 알림은 지출을 자동 차단하지 않는다. VM 정지는 삭제가 아니며 디스크/IP 비용은 남는다. [VM 요금](https://cloud.google.com/products/compute/pricing), [디스크 요금](https://cloud.google.com/compute/disks-image-pricing).

## 발표 후 로컬 전환과 공용 서버 정리

```powershell
./scripts/set-langfuse-target.ps1 -Target local
docker compose up -d --build
```

이 명령은 백업한 로컬 키를 복원하고 로컬 Docker 주소를 사용한다. 로컬 UI는 http://localhost:3000이다. 기존 로컬 조직/trace는 volume에 유지되며 공용 데이터는 자동 복사되지 않는다. `docker compose down -v`는 로컬 데이터를 삭제하므로 사용하지 않는다.

필요한 공용 trace는 UI/API로 내보내고, 전체 복구용으로는 VM을 정지한 뒤 boot disk snapshot을 만든다. 복구 VM에서 Langfuse 조직/trace가 유지되는지 확인한 다음 공용 서버를 정리한다. 삭제는 명시적인 사용자 요청 후 실행한다:

```powershell
gcloud compute instances delete langfuse-shared --zone=us-central1-a --project=proj2-509406
gcloud compute addresses delete langfuse-shared-ip --region=us-central1 --project=proj2-509406
gcloud compute firewall-rules delete langfuse-shared-web --project=proj2-509406
```

보존된 디스크와 snapshot도 계속 과금되므로 필요 없는 항목을 확인해 별도로 삭제한다. `.env.langfuse-gcp` 및 `.env.langfuse-compose.json`에는 비밀값이 있으므로 프로젝트 종료 후 안전하게 보관하거나 삭제한다. 복구용 snapshot에는 모든 공용 계정/trace/서버 비밀값이 포함된다.

## 2026-10-02 검증 기록

- 공용 HTTPS health 200, 초기 관리자 로그인과 프로젝트 페이지 접근 확인.
- 실행 중인 로컬 API 컨테이너의 JobTracer가 공용 서버에 보낸 합성 trace를 v4 Observations API에서 조회했다. LLM 호출 비용 없이 전송/저장을 검증했으며 실제 LLM/Pinterest E2E 검증은 포함하지 않는다.
- 기존 로컬 Langfuse에도 로컬 키로 합성 trace를 보내 저장을 확인했다. 전환 스크립트 테스트에서 공용 전환 반복 후 로컬 키 복원과 다른 환경변수 보존을 확인했다.
- 정지된 VM의 snapshot으로 임시 VM을 복구해 기존 프로젝트와 관측 데이터 유지 확인. 공용 VM 재시작 후 로그인 및 새 trace 저장도 확인했다. 검증용 VM, boot disk, snapshot은 삭제했다.
- PR 전용 main 기준 worktree에서 전환, job trace, LLM adapter 테스트 67개가 모두 통과했다. 기존 작업 브랜치의 별도 LLM 변경은 이 PR에 포함하지 않았다.
