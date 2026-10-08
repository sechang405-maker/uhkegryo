# GCP 팀 공용 Langfuse

## Why
팀원이 발표 기간에 같은 조직에서 trace를 확인해야 한다. 개인 컴퓨터를 켜 두지 않고 공용 서버에 접근하며, 발표 후 비용 리소스를 제거할 수 있어야 한다.

## Goal
GCP Compute Engine Ubuntu VM의 Docker Compose로 기존 Langfuse 저장 서비스를 재사용한다. HTTPS UI, 영구 데이터, 팀 계정을 제공한다. Out of Scope: HA, Kubernetes, 앱 api/mcp의 신규 배포, 기존 로컬 데이터 자동 복사.

## What
VM에서 Langfuse web/worker, PostgreSQL, ClickHouse, Redis, MinIO와 Caddy를 실행한다. 관리자가 조직/프로젝트와 키를 만들고 팀 계정을 연결한다. URL 전환 전 필요한 공용 데이터를 백업한다. VM 정지 시 접속 불가이며 데이터는 디스크에 남는다. VM 삭제 전 백업을 확인한다.

## How
비용 우선으로 us-central1-a의 e2-standard-4(4 vCPU/16 GiB), Ubuntu 24.04, 50 GiB pd-balanced 디스크를 사용한다. 사용자 요청에 따라 단일 VM과 고정 IP를 사용하며 시작 후 4시간 자동 STOP으로 유휴 과금을 줄인다. 50 GiB는 소규모 발표용 시작 용량이며 디스크 사용량을 확인하고 필요시 확장한다. 구매 도메인이 없으면 고정 IP.sslip.io 무료 DNS를 사용하며 이 외부 DNS의 가용성에 의존한다. Caddy가 80/443에서 TLS를 제공하며 DB와 MinIO 포트는 외부에 열지 않는다. 텍스트 trace만 지원하며 브라우저 직접 미디어 업로드는 범위 밖이다. Compose override에서 외부 NEXTAUTH_URL과 Caddy 도메인을 설정한다. 초기 관리자 계정, 조직, 프로젝트, 키는 무작위 비밀값으로 headless 초기화한다. 로컬에 생성하는 .env.langfuse-* 파일은 Git에서 제외한다. VM에는 앱 서비스를 제외한 렌더링된 Compose만 전송한다. 기본 Compose는 자동 백업을 제공하지 않으므로 정지 상태의 디스크 snapshot으로 백업하고 복구 검증한다. 비용에는 VM, 디스크, IP, snapshot, 네트워크가 포함되며 예산 알림은 강제 지출 상한이 아니다. 정지 후에도 디스크와 고정 IP 과금은 계속된다.

## AC
- GIVEN GCP overlay와 도메인 WHEN Compose config 검사 THEN HTTPS URL과 proxy 설정이 유효하다.
- GIVEN 배포된 VM WHEN HTTPS health와 UI 조회 THEN 정상 응답이며 팀 계정으로 같은 프로젝트를 본다.
- GIVEN 공용 키와 URL WHEN 백엔드 job 실행 THEN 공용 UI에 trace가 기록된다.
- GIVEN VM 재시작 WHEN UI 조회 THEN 기존 조직과 trace가 유지된다.
- GIVEN 서버 정지 및 snapshot WHEN 복구 VM 실행 THEN 저장된 조직과 trace를 조회한다.
- GIVEN 백업과 로컬 전환 완료 WHEN 발표 후 VM/불필요 디스크/IP/snapshot 삭제 THEN 공용 비용 리소스 제거와 로컬 trace 수신을 확인한다.
