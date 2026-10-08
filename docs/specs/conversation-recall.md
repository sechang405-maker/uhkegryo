# 과거 대화 회상
## Why
사용자는 오래된 추천을 다시 묻고 근거를 확인해야 한다.
## Goal
동일 대화의 원본 job을 찾아 짧게 답하고 출처를 제공한다. 일반 지식 챗봇/외부 RAG는 제외한다.
## What
회상만 요청하면 Pinterest 검색 없이 memory_answer를 반환한다. 회상과 변경이 함께 있으면 원본 조회 후 일반 해석을 수행하고 회상 답변을 함께 담는다. 회상 대상이 불명확하거나 후보가 과다하면 한 번 확인 질문을 하고, 없으면 확인 불가를 알린다. 혼합 요청은 이런 회상 안내가 있어도 일반 해석으로 진행하며, 새 요청 자체가 과거 대상을 필요로 해 해석할 수 없을 때만 일반 확인 질문을 한다.
## How
adapter의 구조화 recall query는 mode=none/recall/mixed, role/term_id/keywords/start/end/source_job_ids(최대20), latest(bool)다. 조건들은 같은 대화의 선행 completed job에만 적용하며 SQL은 파라미터화한다. 텍스트 검색은 요청/정제결과에 한정한다.
최근6개와 summary 출처를 탐색 후보로 사용하되 명시적 검색 조건을 우선한다. 최대21개를 조회해 20개 초과를 감지한다. latest이면 최신 일치 1개만 조회한다. 빈 검색어는 전체 회상 대상으로 처리하고 초과 시 범위를 묻는다. 타 대화/미래 job ID는 거부한다.
답변 출력은 한국어 answer(최대2000자), citations(job_id,quote)다. quote는 제공한 원본 정제 record에 실제 있어야 한다. 서버가 확인 후 sources(job_id,href=/api/jobs/{id})를 조립한다. 인용 존재만으로 문장 의미가 증명되지는 않으므로 평가에서 별도 확인한다.
AgentResult에 memory_answer(nullable string), sources를 추가한다. 회상 전용 agent_status=memory_answer는 reference_plan=null이고 성공 근거가 있으면 sources 필수다. 근거 없음/범위 질문은 서버 고정 문구와 빈 sources다. 기존 응답은 기본값으로 호환한다.
기록은 untrusted data이며 system 지시로 승격하지 않는다. Pin/URL은 모델에 주지 않는다. 회상만은 validating→rendering→completed이며 검색/조건 갱신하지 않는다.
## AC
- Given 과거 추천, When 회상 질문, Then 짧은 답과 같은 대화 원본 링크를 반환한다.
- Given 20개 초과 후보, When 전체 회상, Then 전체를 봤다고 주장하지 않고 범위를 묻는다.
- Given 없는 기록/조작 인용/다른 대화 출처, When 응답, Then 허위 출처를 표시하지 않는다.
- Given 회상만, When 처리, Then search 미호출, constraints 불변이다.
- Given 회상+변경, When 처리, Then 조회 근거를 사용해 새 결과를 생성한다.

명백한 새 시각 요청의 classify 생략 조건은 [conversation-recall-fast-path.md](conversation-recall-fast-path.md)를 따른다.
