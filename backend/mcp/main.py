"""MCP 독립 엔트리포인트 (내부 서비스 전용).

Cloud Run `mcp` 서비스의 진입점.
공개 API(/health, /api/*)와 분리되어 배포됨.
인증: Cloud Run IAM (--no-allow-unauthenticated + roles/run.invoker)
"""
from mcp_server.server import app

# uvicorn mcp_server.server:app --host 0.0.0.0 --port 8000
