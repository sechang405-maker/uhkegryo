"""백엔드 서비스 계층 (backend.services).

결정론 규칙(카탈로그 로드·해석 검증·검색 URL·응답 조립)을 담당한다.
LLM 호출은 services/llm.py 하나에서만 하고, 라우터·worker가 이 계층을 소비한다.
"""