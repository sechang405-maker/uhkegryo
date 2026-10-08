# 평가 리포트 — UH케그려 (4조)

2026-10-03 기준. 구현·자동 검사·외부 연결·정성 점수를 구분한다. 검증하지 않은 값은 미측정으로 표시한다. 제출 전 최종 배포 commit과 운영 결과를 추가해야 한다.

## 1. 구현과 관측

| 항목 | 구현·검증 근거 | 남은 확인 |
| --- | --- | --- |
| API·영속화·worker | PostgreSQL 세션/Job, claim·retry·lease recovery, cookie 소유권 구현 | 최종 운영 API E2E |
| MCP·검색 | 카드 조회와 검색 도구, worker tool calling 구현. 후보 코드 ddd7f93에서 실제 검색 연결 확인 | 최종 main·브라우저 연결 재검증 |
| UI | 입력·polling·답변·용어·Pin 썸네일·대화 이력 구현 | 실제 운영 화면 검증 |
| Langfuse trace | job/session·attempt·단계·실패, LLM generation·토큰 기록 코드 구현 | 실제 서비스 요청의 입출력·비용·지연 수집 |
| 공용·로컬 수신 | PR #108: HTTPS health, 합성 JobTracer trace 양쪽 저장·로컬 키 복원·snapshot 복구 검증 | PR #108은 병합됨. 실제 LLM 요청 관측은 별도 미검증 |

근거: [MCP 운영 호출](docs/mcp-client-evidence.md), [검색 연결 검증](docs/specs/local-agent-search-verification.md), [Langfuse 운영 기록](https://github.com/aihuman-7th/proj2-4/pull/108). 합성 trace 수신은 실제 모델 관측이나 Dataset 평가 완료를 의미하지 않는다. 일반 로그에는 사용자 원문·키·쿠키를 남기지 않는다.

## 2. 프롬프트 운영

- 해석 프롬프트 v0~v4와 파일 로딩·버전 태깅 구현.
- 배포 구성과 현재 로컬 설정을 `openai/gpt-4.1-mini`, `uhkegryo-interpreter-v4` 경로·버전으로 정렬했다. 실제 Cloud Run 적용은 미확인이다.
- Langfuse 원격 Prompt 등록·production label 조회·무배포 교체·롤백: 미검증. 현재 adapter는 파일을 읽는다.
- 고정할 정보: 최종 commit, prompt SHA-256, 모델, 카탈로그 버전, dataset SHA-256, judge/rubric 버전.

## 3. 평가셋과 판정

- 고정 원문 30건: 정상 10 / 경계 6 / 실패 유도 6 / PRD 흐름 8.
- 추가 모호성·상충 대조 10건. 계약 변형 70건과 원문 30건은 별도의 100건 계약 평가 입력이며 전체 실행 결과는 미측정이다.
- [rubric](evals/rubric-and-baseline.md): 계약·안전 pass/fail, 용어·역할/초보자 안내/질문·다음 행동 각각 0~2점.
- 도메인 평가자 오세창 + 독립 사람 검토자 또는 생성 모델과 다른 judge. 정성 점수·judge 일치도·틀림 포착률·kappa는 미산정이다.
- Langfuse Dataset 등록·run 연결은 미검증이다.

## 4. 실제 모델 평가와 개선 과정

| 실행 | 검사 결과 | 발견·조치 |
| --- | --- | --- |
| 10/2 15:23 | 13/15 | 의상 효과 단정, 회상 필터 한도 오류 |
| 15:26 | 14/15 | 의상 대조 예시 보강 |
| 15:29 | 15/15 | 사용하지 않는 회상 필터 정규화 |
| 15:31 | 34/40 | 중복 역할과 범위 밖 종결 저장 오류 |
| 15:40 | 39/40 | 재시도 피드백·저장 수정 후 과도한 재질문 확인 |
| 15:45 | 40/40 | 명시적 체중 지지와 같은 방향 기울기 구분 보완 |

이 과정은 탐색적 개선 기록이다. 여러 코드·프롬프트 변경이 포함되어 단일 변수의 인과 비교로 주장하지 않는다. 최종 제출 비교는 같은 모델·데이터셋·rubric에서 한 변수만 바꿔 baseline과 후보를 다시 측정해야 한다. 과거 반복 실행 일부는 원래 작업 폴더에 있으며 저장소에는 최종 실행 자료를 포함한다.

이전 작업 트리의 참고 실행: GPT-4.1-mini·v4·카탈로그 `0.8-json-runtime-catalog-reviewed`, 원문 **30/30**, 대조 **10/10** 기대값 일치. [보고서](evals/runs/20261002-154511-openai-gpt-4.1-mini/report.md), [실제 답변](evals/runs/20261002-154511-openai-gpt-4.1-mini/review.md), [metadata](evals/runs/20261002-154511-openai-gpt-4.1-mini/metadata.json).

실제 PostgreSQL·worker·LLM adapter·resolver·assembler를 사용하고 검색은 fixture다. HTTP/cookie·MCP 네트워크·실제 Pinterest·Langfuse·정성 품질은 이 평가에서 제외했다. dirty 작업 트리의 소스 지문으로 기록됐으며 최신 main 통합 후 모델 40건 재실행 결과가 아니다. 따라서 전체 서비스 계약 준수율이나 품질 100점으로 환산하지 않는다.

### 과거 실행과 현재 배포 파일의 지문 차이

| 파일 | 10/2 실행 metadata의 source_sha256 | PR #110 코드 기준 466e0a8 Git 파일(LF)의 SHA-256 |
| --- | --- | --- |
| prompts/uhkegryo-interpreter-v4.md | 7b3ded9dc1420ea0c34b060692ea63f6d97632ca8103300eaf246eacbf289241 | 975749ff4435d008b5432963b7f718c9df7f5e705cb475573310b282b0cca2fb |
| backend/services/llm.py | 3bdb2381d27562587a771e83ce621e495685c5ea8a50c36b7ea6023114272a78 | 3791f51386587fe04e107c2602b9d024880280491eeb3da41708106aa0b2e57b |

비교 열은 PR #110 코드 기준 466e0a8에 고정한 Git blob이며, 이후 head의 현재 해시를 의미하지 않는다. Windows checkout CRLF 해시와 혼동하지 않는다. 과거 실행은 dirty 소스 지문이며 이 표만으로 차이의 원인을 추정하지 않는다. 40/40·비용·지연을 현재 배포 후보의 통과 근거로 사용하지 않는다. 현재 PR에서는 실제 모델 평가를 재실행하지 않았다.

## 5. 비용·지연과 모델 선택

| 지표 | 10/2 15:45 실제 모델 평가 |
| --- | --- |
| 모델 응답 수 | 69회 (기억 분류·해석·재시도 포함) |
| 총 토큰 | 671,273 |
| 제공자 기록 총 비용 | $0.2420096 |
| 문항 지연 p50 / p95 | 4.61초 / 9.89초 |
| 요청당 운영 비용·완료율 | 미측정 |

GPT-4.1-mini·v4는 이전 작업 트리에서 얻은 참고 결과를 바탕으로 배포 후보 설정으로 선택했다. 현재 PR의 프롬프트·어댑터 지문은 그 실행과 다르며, 현재 커밋의 조합이 40/40을 통과했다는 근거는 없다. 현재 PR의 실제 모델 품질은 동일 평가 재실행 전까지 미검증이다. 위 비용·지연은 검색 fixture 평가값이며 실제 외부 검색과 UI를 포함한 운영 수치가 아니다. 동일 조건의 모델 간 품질·비용 비교는 아직 필요하다.

## 6. 외부 연결 증거

- 9/29 MCP Cloud Run revision `mcp-00006-fh9`: 무인증 403, 인증된 카드 목록·found·not_found 통과. 현재 검색 도구 전체의 운영 검증으로 확대하지 않는다.
- 10/2 후보 ddd7f93: API → LLM tool calling → MCP → SearXNG → widget 연결, body/pose 각 Pin 8개, 썸네일 HEAD 16개 모두 200·이미지 Content-Type, MCP CallToolRequest 4건 확인.
- 후보 검증은 frontend 프록시·실제 브라우저·Langfuse·이미지 의미 적합성 평가를 제외했다. 최종 main E2E는 미검증이다.
- PR #108 head 9d2a5a3: backend CI 486 passed / 29 skipped, Secret Scan 통과. Windows 관련 테스트 67 passed. [CI](https://github.com/aihuman-7th/proj2-4/actions/runs/37121313909).

- 10/3 배포 설정 정렬 후 로컬 backend 전체 회귀: **487 passed / 28 skipped**. 외부 전송 비활성화 테스트이며 DB·Docker·실제 네트워크 검증의 대체가 아니다. 환경 변수 예시·로컬 설정의 모델/버전 및 v4 파일 파싱 확인. 실제 이미지 빌드·배포는 미실행.

## 7. 출시 게이트와 제출 상태

| 게이트 | 기준 | 현재 |
| --- | --- | --- |
| 전체 계약 준수 | 95% 이상 | 미측정; 기대값 40/40과 구분 |
| 운영 p95·요청당 비용 | 팀이 평가 전 상한 확정 | 미확정·미측정 |
| 유해·거부 오작동 | 고정 안전 평가에서 0건 | 최종 운영 검증 필요 |
| 배포 URL·정상/실패 UI | 외부 접속·종결 확인 | 사용자 UI/API URL 미기록 |
| Langfuse 증거 | 실제 trace 상세 포함 화면 3장 이상 | 제출용 화면 미정리 |
| 데모 영상 | 정상·실패 각 1건 | 미제작 |

## 8. 약점과 다음 검증

최종 통합 서비스와 외부 검색의 재현성·정성 품질을 아직 입증하지 못했다. 외부 검색은 결과·지연이 변하고 원격 썸네일이 사라질 수 있다. 질문의 단어 조합 자동 검사는 이해하기 쉬운지와 적절한지까지 보장하지 않는다. [실제 서비스 검증 절차](docs/service-validation-guide.md)에 따라 최종 코드에서 연결·관측·정성 평가를 수행하고 이 문서를 갱신한다.

PR 분리 검증(2026-10-03): origin/main a0c49f7 기반에서 PR #108 미커밋 파일을 제외한 이번 변경만으로 backend 483 passed / 28 skipped. 실제 외부 연결·품질 검증은 실행하지 않았다.
