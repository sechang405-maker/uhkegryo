# 실제 서비스·외부 검색·관측·정성 평가 절차

이 문서는 실행 안내이며 새로운 성공 기록이 아니다. 외부 API 호출 비용과 서버 기동은 운영자가 확인한다. 최종 commit·모델·프롬프트·카탈로그·dataset·rubric을 고정한 뒤 실행한다.

## 1. 실행 설정

로컬 `.env`에서 아래 세 값을 함께 설정한다. 비밀값은 기존 `.env.example`에 있는 변수명만 참고해 로컬에 입력한다.

```dotenv
LLM_MODEL=openai/gpt-4.1-mini
INTERPRETER_PROMPT_PATH=./prompts/uhkegryo-interpreter-v4.md
INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4
```

개발용 DB migration은 [README](../README.md)의 현재 migration runner를 사용한다. 공유 운영 DB에 임의 적용하지 않는다. 공용 Langfuse는 기동 여부와 HTTPS health를 먼저 확인한다. #108 구성에서는 시작 후 4시간 자동 정지하므로 평가 중 수신 가능한지 확인한다.

```powershell
docker compose config --quiet
docker compose up -d --build
# 다른 터미널에서 frontend 실행
cd frontend
npm ci
npm run dev -- --port 3001
```

## 2. 실제 MCP·Pinterest 연결

1. [연결 검증 Spec](specs/local-agent-search-verification.md)의 MCP health·도구 목록 명령을 실행한다. `get_active_term_card`, `search_pinterest_pins`가 실제 transport로 조회되어야 한다.
2. 브라우저 `http://localhost:3001`에서 아래 입력을 제출한다. 실제 API 모드이며 demo 응답을 사용하지 않는지 확인한다.
3. Network에서 POST 202·queued, 같은 쿠키의 polling, completed/result 또는 failed/failure를 확인한다.
4. MCP 로그의 실제 CallToolRequest와 검색 결과를 확인한다. 역할별 최대 8개, 원본 Pin URL·미리보기 상태, 빈 결과/실패 사유 코드를 확인한다.
5. 썸네일은 브라우저 렌더링과 HEAD의 이미지 Content-Type을 확인한다. 이미지 파일·썸네일 URL을 평가 기록으로 저장하지 않는다. 결과 개수는 외부 상태에 따라 바뀌므로 항상 8개일 것을 성공 조건으로 삼지 않는다.

| 입력·조건 | 확인할 동작 |
| --- | --- |
| 마른 캐릭터가 한쪽 다리에 체중을 싣고 서 있는 자세 레퍼런스를 찾아줘 | 명시된 body/pose 해석, 실제 Pin과 쉬운 설명 |
| 어깨가 망토 때문에 넓어 보이는 캐릭터 | 체형 단정 없이 필요한 단서 질문, 검색 없음 |
| 올린 그림을 분석해서 캐릭터를 생성해줘 | 범위 밖 안내, 불필요한 LLM/검색 없음 |
| 격리 환경에서 SearXNG 중단 후 명확한 요청 | partial_result 또는 계약된 실패, 원인·다음 행동 안내 |

최종 코드 SHA·이미지 digest·일시·환경·종결 상태·역할별 Pin 수·안전한 오류 코드를 기록한다. 기존 후보 코드의 16개 Pin 결과를 새 버전 결과로 복사하지 않는다.

## 3. 실제 Langfuse 수신과 지표

- API가 쓰는 LANGFUSE_HOST/BASE_URL과 해당 프로젝트 public/secret key를 맞추고 API를 재생성한다. 키나 전체 Compose 렌더링 결과를 출력하지 않는다.
- 실제 브라우저 요청 후 trace에서 job/session, 모델, v4 버전, attempt·단계, generation 토큰·입출력, 최종 상태·실패를 확인한다. 합성 trace 스크립트 통과만으로 완료하지 않는다.
- 같은 job의 재시도가 연결되는지, LLM과 검색 중 어느 구간이 느린지 확인한다. generation model 매핑과 가격 설정을 확인해 비용이 누락된 경우 0원으로 기록하지 않는다.
- 최소 대시보드·정상 trace 상세·실패/재시도 화면 3장을 저장한다. 키·쿠키·개인 요청은 제외한다.
- 시작은 제출 시각, 종료는 terminal polling 수신 시각으로 정해 운영 p50/p95를 계산한다. job당 모든 모델 호출 비용을 합산한 평균과 성공/부분/실패 비율을 함께 기록한다.

`scripts/run_live_eval.py`는 검색을 fixture로 교체하고 Langfuse key를 비워 전송하지 않는다. 기존 runner를 실행해도 실제 MCP·Pinterest·Langfuse 평가가 되지 않는다. 외부 검증은 실제 API/브라우저 경로로 수행한다. 도구 timeout·worker 중단 등 강제 장애 문항은 격리 fixture 평가와 구분한다.

## 4. 정성 품질

- 기존 review.md는 텍스트 품질 검토에 사용하고, 실제 검색 품질은 새 API 결과를 브라우저에서 확인한다.
- 오세창과 독립 검토자 1명이 [고정 rubric](../evals/rubric-and-baseline.md)으로 용어·역할, 초보자 안내, 질문·다음 행동을 각각 0~2점과 이유로 독립 채점한다.
- 이미지 검색은 선택 역할에 맞는 관찰 단서가 보이는지 검토하고 적합/부적합/판정 불가 개수를 기록한다. 기준을 실행 전에 고정한다. 이미지나 썸네일을 저장하지 않는다.
- 기록: eval_id, run_id, 적용 축, 각 평가자 점수·이유, 불일치와 합의 결과. 적용되지 않는 축은 N/A로 두고 평균에서 제외한다.
- judge 사용 시 생성 모델과 다른 모델을 선택하고 사람 판정과 일치도·틀림 포착률·kappa를 측정한다. 기준 미달이면 사람 판정을 최종 근거로 사용한다.

## 5. 최종 제출 비교

동일 모델·dataset·judge를 고정하고 프롬프트 또는 코드 규칙 한 가지만 변경한다. baseline/후보 각각을 실행해 문항별 변화·회귀·지연·비용·KEEP/DISCARD를 기록한다. 인젝션 최소 3건은 같은 판정 기준으로 전후 비교한다. 수정 후 전체 회귀를 다시 확인하고 [EVAL_REPORT](../EVAL_REPORT.md)에 실제 수치·trace 링크·검증 한계를 추가한다. Prompt 원격 등록·롤백은 현재 파일 로딩과 별도 작업이며 완료 전 운영 완료로 표시하지 않는다.
