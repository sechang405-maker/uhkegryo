# 로컬 Ollama 포트폴리오 설계

## 목표

유료 외부 LLM이나 개인 Codex 인증을 사용하지 않고, 운영자 노트북의 GPU에서
`qwen3.5:4b-q4_K_M`을 실행한다. 기존 어케그려의 카탈로그, RAG 성격의 활성 카드
주입, Pydantic 검증, 비동기 worker, 검색과 그래프 UI는 유지한다. 이번 단계는 로컬
모델 설치·연결·30개 고정 질문 평가까지이며, 외부 터널과 방화벽 변경은 포함하지 않는다.

## 검토한 접근

1. 기존 OpenRouter 설정값만 localhost로 바꾼다. 변경량은 작지만 공급자 경계가
   숨겨지고, 포트폴리오의 무료 외부 모델 예산 코드와 로컬 실행이 섞인다.
2. `ollama`를 명시적인 LLM 백엔드로 추가하고 기존 OpenAI 호환 어댑터의 계약을
   재사용한다. 설정 검증에서 loopback URL, 정확한 모델 태그, worker 동시성 1을
   강제하고 클라우드 fallback을 금지할 수 있다. **이 방식을 채택한다.**
3. llama.cpp 전용 서버와 새 클라이언트를 도입한다. 세밀한 제어는 가능하지만 이미
   설치된 Ollama와 기존 OpenAI 호환 계층을 버리고 운영 요소를 늘리므로 현재 범위에는
   맞지 않는다.

## 아키텍처와 데이터 흐름

`LLM_BACKEND=ollama`일 때 worker는 기존 `LLMInterpretationAdapter`를 사용하되,
클라이언트의 base URL을 `http://127.0.0.1:11434/v1`로 고정 검증하고 API key에는
Ollama가 무시하는 로컬 자리표시자만 전달한다. 요청 모델은
`qwen3.5:4b-q4_K_M`, 추론 제어는 `reasoning_effort=none`, 출력 상한은 기존 설정을
사용한다. Ollama의 기본 context 4096을 유지하며 별도 파생 모델은 만들지 않는다.

활성 TERM_CARD JSON과 대화 문맥을 넣는 기존 prompt, Pydantic
`InterpretationOutput`, resolver와 검색은 변경하지 않는다. 개인 용어 생성 등 같은
어댑터를 쓰는 호출도 로컬 모델을 사용한다. `anonymous_portfolio` 모드에서는
OpenRouter와 Ollama를 서로 다른 허용 경계로 검증하며, Ollama 선택 시 외부 모델
allowlist·API key·가격 카탈로그·일일 외부 호출 예산을 요구하지 않는다.

## 보안과 운영 경계

- Ollama base URL은 `localhost`, `127.0.0.1`, IPv6 loopback만 허용하고 credentials,
  query, fragment를 거부한다.
- 모델 이름은 정확히 `qwen3.5:4b-q4_K_M`만 허용한다. `:cloud` 또는 원격 공급자
  fallback은 없다.
- worker 동시성은 1이며 Ollama는 기본 loopback bind를 유지한다.
- Langfuse 질문 추적, 개인 Codex 인증, 원본 팀 GCP 자원은 사용하지 않는다.
- 외부 터널, 공유 secret, Vercel gateway 환경값은 후속 승인 전에는 만들거나 바꾸지
  않는다.

## 평가

고정된 합성 질문 30개를 네 묶음으로 관리한다: 한국어 일러스트 용어 설명,
구도·투시·체형·포즈 조합, 검색어 재작성과 신규 용어 구조화, 근거 부족·모호성·범위
밖 요청. 모델 단독 구조화 평가는 기존 활성 카탈로그와 v4 prompt를 주입해 실행하고,
앱 RAG/worker 통합 평가는 별도로 표시한다.

각 케이스는 한 번만 생성한다. 상태, 필수/금지 term ID, JSON/Pydantic 유효성,
지연시간, 모델 식별자와 오류 범주를 기록한다. 자동 점수는 구조적 계약만 판정하고
한국어 설명 품질은 원문을 보존한 검토 파일에서 사람이 확인한다. 민감한 환경값,
대화 데이터, 원시 예외의 비밀 문자열은 기록하지 않는다.

## 실패와 취소

연결 실패·timeout·잘못된 JSON은 기존 failure mapping을 유지한다. 평가 러너는 기존
출력 디렉터리를 덮어쓰지 않고, 실패 케이스를 자동 재시도하지 않으며, 중단되면 남은
케이스를 `not_run`으로 구분한다. 실제 worker의 재시도·취소·lease 회수는 기존 회귀
테스트로 확인하고 이번 변경에서 정책을 확장하지 않는다.

## 완료 기준

- 설정 단위 테스트가 loopback 전용, 정확한 모델, 외부 fallback 금지를 증명한다.
- 어댑터 테스트가 Ollama 클라이언트와 `reasoning_effort=none` 요청을 증명한다.
- 30개 평가 결과에 정확한 모델 태그·양자화·설치 크기·응답시간·구조 통과 여부가
  포함된다.
- `ollama ps`와 `nvidia-smi`로 실제 CPU/GPU 분담과 VRAM을 측정한다.
- 관련 테스트, 전체 백엔드 회귀, 프론트엔드 테스트·빌드를 실행해 결과를 구분한다.
- 검증된 변경만 개인 저장소 `main`에 직접 커밋·푸시하고 CI와 Vercel 상태를 확인한다.

