# 외부 MCP client 호출 증거 (작업 16)

## 검증 범위와 현재 상태

- 2026-09-29, Windows / Python 3.14, `backend.mcp.main:app` 기준 `72eccec`에서 별도 프로세스의 MCP Python SDK client가 마운트된 Streamable HTTP `/mcp`에 접속했다.
- 마운트된 FastAPI 앱 로컬 실행: tool 목록, 활성 카드 `found`, 미등록 카드 `not_found` 검증 **통과**. 부모 FastAPI lifespan에서 FastMCP session manager가 시작되도록 수정해 이전 HTTP 500을 해결했다.
- Cloud Run 배포: `proj2-509406` / `asia-northeast3`, 서비스 `mcp`, revision `mcp-00006-fh9`, URL `https://mcp-fgdrdxsn6q-du.a.run.app`.
- 2026-09-29 운영 IAM 검증: 무인증 요청 **403**, 임시로 `roles/run.invoker`를 부여한 인증 호출에서 도구 목록·`found`·`not_found` **통과**. 검증 직후 임시 사용자 권한을 제거했으며, 최종 서비스 IAM 정책에는 `mcp-caller@proj2-509406.iam.gserviceaccount.com`만 등록돼 있다.
- Cloud Run IAM 앞단 인증 이후 FastMCP Host 검증도 통과하도록 `MCP_ALLOWED_HOST`에 Cloud Run hostname을 설정했다. 로컬 loopback Host 허용은 유지한다.

## 로컬 재현

저장소 루트에서 터미널 두 개를 사용한다. 첫 터미널:

```powershell
python -c "from backend.mcp.server import mcp; mcp.settings.host='127.0.0.1'; mcp.settings.port=8765; mcp.run(transport='streamable-http')"
```

둘째 터미널 (서버 코드 내부 함수가 아닌 별도 MCP client 프로세스):

```powershell
python scripts/mcp_client_evidence.py
```

2026-09-29 실행 출력 (`8765` 포트가 점유되어 당시에는 `8766`을 사용):

```json
{
  "tools": ["get_active_term_card"],
  "found": {
    "status": "found",
    "catalog_version": "0.8-json-runtime-catalog-reviewed",
    "term_id": "pose_contrapposto",
    "role": "pose"
  },
  "not_found": {
    "status": "not_found",
    "reason_code": "TERM_NOT_ACTIVE"
  }
}
```

스크립트는 실제 `list_tools`·`call_tool` 결과를 계약 필드와 대조한 뒤 위 최소 결과만 출력한다. 토큰, 세션 ID, 카드의 검색 조각은 출력하지 않는다. 반환 코드 0은 세 검증 통과를 뜻한다.

## Cloud Run 배포 후 접근 제어 재현

Cloud Run `mcp` 서비스는 IAM 보호(`--no-allow-unauthenticated`)로 배포한다. 허용 호출자 서비스 계정에는 `roles/run.invoker`가 필요하다. 다음 PowerShell 절차는 허용 호출자 서비스 계정 impersonation 권한을 가진 운영자가 실행한다.

```powershell
$mcpServiceUrl = gcloud run services describe mcp --region=asia-northeast3 --project=proj2-509406 --format='value(status.url)'
$env:MCP_ID_TOKEN = gcloud auth print-identity-token --impersonate-service-account='mcp-caller@proj2-509406.iam.gserviceaccount.com' --audiences=$mcpServiceUrl
python scripts/mcp_client_evidence.py --url "$mcpServiceUrl/mcp" --check-denied
Remove-Item Env:MCP_ID_TOKEN
```

`--check-denied`는 **무인증 초기화 요청이 401 또는 403**인지 먼저 확인하고, 같은 endpoint에 ID token을 넣어 도구 목록·`found`·`not_found`를 호출한다. 성공하면 출력에 `anonymous_http_status`가 추가된다. 실제 운영 실행 날짜, 서비스 URL, 상태 코드와 축약 결과를 이 문서 및 데모에 기록해야 한다. ID token 값과 전체 HTTP 헤더는 기록하지 않는다.

## 연결 정보

| 항목 | 값 |
| --- | --- |
| Transport | Streamable HTTP |
| Endpoint | 로컬 `http://127.0.0.1:8765/mcp`; 운영 `<mcp service URL>/mcp` |
| Tool | `get_active_term_card(term_id: str)` |
| 인증 | 로컬 단독 실행에는 없음; 운영 Cloud Run IAM ID token |
| Client | `scripts/mcp_client_evidence.py` (`mcp` Python SDK의 `ClientSession`) |

브라우저와 Next.js UI는 MCP에 직접 연결하지 않는다. 위 운영 결과는 2026-09-29 배포 revision에서 재현했다.
