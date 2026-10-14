# Local Codex Luna Implementation Plan

**Goal:** 개인 Windows 호스트의 기존 ChatGPT 로그인 Codex CLI로 어케그려 답변을 생성한다.

**Architecture:** 밀리테크의 검증된 공식 CLI 탐색·로그인 확인·ephemeral JSON 출력 패턴을 따른다. 기존 LLM adapter의 prompt 구성과 Pydantic 검증은 상속하고 전송만 교체한다. 로컬 launcher는 loopback API/DB, worker 1개, 외부 trace/검색 비활성화를 강제한다. 기존 OpenRouter 및 독립 demo는 유지한다.

**Tech Stack:** Python asyncio subprocess, 기존 Pydantic/FastAPI, 공식 Codex CLI.

## Global Constraints

- 모델 `gpt-5.6-luna`, reasoning low. 모델/provider 실측이 다르면 실패한다.
- 인증 파일·토큰 직접 읽기, 로그인 생성/변경, API 과금 fallback 없음.
- 합성 입력으로 실제 interpret 호출 1회만 허용. 나머지는 mock.
- CLI 호출 timeout 180초, 동시 실행 1개, adapter 자체 재시도 없음. job의 기존 최대 3회 정책만 유지.
- 데이터 삭제·보관기간 변경·공개 배포 없음. 구독 사용량 소비와 OpenAI로 전송되는 입력 범위를 문서화한다.

## Implementation

1. `backend/tests/test_codex_local.py`: 환경 필터, signed binary 선택, subprocess 취소/timeout, 모델 일치, JSON 검증, local guard를 먼저 테스트한다. 신설 기능 부재로 실패함을 확인한다.
2. `backend/services/codex_runtime.py`: 공식 설치 폴더에서 서명 확인, shell=False 호출, login status 확인, 도구 차단, stdin 입력, JSON schema, bounded stderr, timeout/취소 cleanup을 구현한다.
3. `backend/services/codex_llm.py`: 기존 adapter 상속, interpretation/recall 출력 검증 유지, no OpenRouter 생성, 동시 CLI 1개. `llm.py`의 memory schema hook과 worker provider 선택만 작게 수정한다.
4. `backend/shared/config.py`, `backend/local_codex.py`, `backend/main.py`: 명시적 backend 선택, local 주소 검증, loopback Host/Origin/peer guard, 단일 worker launcher. 독립 local DB Compose 및 실행 문서 작성; 실제 DB 생성/마이그레이션은 실행하지 않는다.
5. mock 회귀 전체, 72개 프런트 테스트, 합성 interpret 1회 및 독립 읽기 전용 코드 검토를 수행한다. 검증한 파일만 개인 main에 expected_sha 조건으로 반영하고 CI/원격 내용을 재확인한다.
