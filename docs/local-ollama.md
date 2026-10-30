# 로컬 Ollama 실행과 측정

## 현재 결론

`qwen3.5:4b-q4_K_M`을 무료로 내려받아 운영자 노트북 GPU에서 실행할 수 있다.
Ollama API는 `http://127.0.0.1:11434/v1`에만 연결하며 OpenRouter, Codex 구독,
Ollama cloud fallback을 사용하지 않는다. 기존 활성 TERM_CARD 주입, v4 prompt,
Pydantic 검증과 resolver는 그대로 사용한다.

다만 2026-10-30 고정 30문항 평가에서 모델 기반 26건 중 스키마를 통과한 해석은
2건뿐이었다. 17건은 `LLM_INVALID_STRUCTURED_OUTPUT`, 1건은
`LLM_UPSTREAM_UNAVAILABLE`, 개인 용어 6건은 JSON 또는 안전 콘텐츠 검증을 통과하지
못했다. 결정론 gate 4건은 모두 통과했다. 이 결과만으로 현재 4B 모델을 공개 평가용
품질로 승인하지 않는다.

같은 입력을 같은 모델로 최소 비교한 결과도 기록했다. 현재 설정
(`reasoning_effort=none`, 800, JSON Schema)은 442 completion token에서 `stop`했지만
`select_terms`와 함께 빈 `clarifying_question`, clarification type을 동시에 내어
`state_rules`에 실패했고, `body_slim` 대신 `body_triangle`을 선택했다. 출력 상한을
1600으로 늘려도 442 token의 같은 실패가 재현되어 현재 실패의 주원인은 잘림이
아니다. thinking 기본값은 800 token에서 `length`로 끝나고 content가 비었으며, 단순
JSON mode는 29 token만에 필수 계약 필드를 누락했다. 따라서 JSON Schema는 출력 형태를
유도하지만 이 4B 모델의 교차 필드 규칙과 의미 선택까지 보장하지 못했다.

## 설치·확인

Windows용 Ollama 0.40.13에서 다음 한 모델만 평가했다.

```powershell
ollama pull qwen3.5:4b-q4_K_M
ollama show qwen3.5:4b-q4_K_M
ollama ps
```

설치 표시 크기는 3.3GB, 모델은 4.2B Q4_K_M이다. 실제 warm-up 뒤 `ollama ps`는
`100% GPU`, context 4096을 표시했다. RTX 5060 Laptop 8GB에서 `nvidia-smi`의
사용 VRAM은 유휴 212MiB에서 4,232MiB로 늘었다. 이 수치는 같은 PC의 해당 측정이며
다른 환경의 보장은 아니다.

## 호스트에서 평가

저장소 전용 가상환경을 만든 뒤 의존성을 설치한다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

dry-run은 모델을 호출하지 않고 데이터·prompt·카탈로그 지문만 기록한다. 실제 실행은
`--execute`를 명시해야 하며 30개 ID를 고정 순서로 모두 전달해야 한다.

```powershell
.\.venv\Scripts\python.exe -m scripts.run_ollama_eval `
  --case-ids OLLAMA-01,OLLAMA-02,OLLAMA-03,OLLAMA-04,OLLAMA-05,OLLAMA-06,OLLAMA-07,OLLAMA-08,OLLAMA-09,OLLAMA-10,OLLAMA-11,OLLAMA-12,OLLAMA-13,OLLAMA-14,OLLAMA-15,OLLAMA-16,OLLAMA-17,OLLAMA-18,OLLAMA-19,OLLAMA-20,OLLAMA-21,OLLAMA-22,OLLAMA-23,OLLAMA-24,OLLAMA-25,OLLAMA-26,OLLAMA-27,OLLAMA-28,OLLAMA-29,OLLAMA-30 `
  --source-commit <40자리 검토 커밋 SHA> `
  --output <새 결과 폴더> `
  --execute
```

기존 결과 폴더는 덮어쓰거나 이어 쓰지 않는다. 모델 기반 문항은 한 번만 호출하고
자동 재시도하지 않는다. 구성 오류가 나면 이후 모델 호출은 `not_run`으로 남는다.

## 앱 연결 설정

호스트에서 Python 백엔드를 실행할 때만 다음 공급자 값을 사용한다.

```powershell
$env:LLM_BACKEND = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
$env:OLLAMA_MODEL = "qwen3.5:4b-q4_K_M"
$env:WORKER_CONCURRENCY = "1"
```

`anonymous_portfolio`에서는 정확한 모델 태그와 loopback URL만 허용하며 OpenRouter
키·무료 모델 allowlist·가격 카탈로그를 거부한다. 요청은
`reasoning_effort=none`으로 전송된다. 기존 job 재시도와 개인 용어 idempotency는
유지하지만 새 LLM 응답 캐시는 추가하지 않았다. 저장된 이전 답변을 다시 여는 UI는
기존처럼 새 모델 호출을 만들지 않는다.

## 아직 연결하지 않은 공개 경로

현재 `compose.portfolio.yml`은 OpenRouter 전용이며 API가 컨테이너 안에서 실행된다.
컨테이너의 `127.0.0.1`은 Windows 호스트 Ollama가 아니므로, 이 파일을 Ollama용으로
바꿨다고 간주하면 안 된다. Ollama를 `0.0.0.0`에 bind하거나 방화벽을 열어 이 문제를
우회하지 않는다.

Vercel 화면에서 노트북의 로컬 모델까지 연결하려면 컨테이너-호스트 경계를 별도로
설계하고, gateway secret과 정확한 HTTPS origin을 만든 다음 외부 터널을 열어야 한다.
외부 터널 실행, 방화벽 변경, secret 생성·등록, Vercel 환경 변경은 이번 단계에서
수행하지 않았다.

## 중지와 재시작

모델 메모리만 내리려면 다음 명령을 사용한다.

```powershell
ollama stop qwen3.5:4b-q4_K_M
```

Ollama 서버를 다시 시작해도 다운로드한 모델은 남는다. 앱의 실패·취소·lease 회수는
기존 worker 정책을 따르며 평가 러너는 실패 문항을 자동으로 재실행하지 않는다.
