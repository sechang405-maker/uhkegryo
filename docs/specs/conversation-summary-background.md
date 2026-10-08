# 자동 요약 제거와 원본 기반 대화 기억
## Why
사용자의 핵심 작업은 최근 요청의 조건 유지와 레퍼런스 검색이다. 일반 대화 요약은 원본 검색 이력을 대신하지 못하며 추가 LLM 비용·길이 실패·백그라운드 작업을 만든다. 요약 호출 수 0과 최근 조건/원본 회상의 유지 여부를 검증한다.
## Goal
자동 요약 생성 및 모든 본문/회상 프롬프트의 요약 입력을 제거한다. 현재 constraints, pending_question, 최근 6개 종결 원문, 검증된 원본 출처와 검색 결과를 유지한다. 오래된 취향의 자동 종합, 회상 검색 확장, UI/API/배포/운영 데이터 일괄 삭제는 제외한다.
## What
새 요청은 현재 조건과 최근 원문으로 해석한다. 명시적 과거 질문은 같은 대화의 전체 선행 원본에서 기존 필터로 조회하고 인용을 검증한다. 26개를 넘는 대화의 오래된 기록도 원본 검색 범위에 포함한다. 모호한 오래된 지시에는 확인 질문을 사용한다. 요청 완료/서버 시작/유휴 상태에는 요약 작업이 없다.
## How
- worker의 SummaryRequests, 결과 저장 후 등록, 요약 루프 시작/종료를 제거한다. 일반 Job 처리·lease 복구·MCP 도구 캐시 갱신은 유지한다.
- conversation_summary_worker 및 SummaryOutput을 제거한다. memory는 classify/answer만 허용하며 summarize 요청은 LLM 호출 전에 거부한다.
- prepare는 memory.load만 수행한다. 오래된 요약 후보 조회, 입력 hash, watermark, 요약 필요 여부 계산, oldest_recent 경계를 제거한다.
- prompt_context는 constraints/pending_question/recent/sources만 반환한다. summary/summary_sources/summary_incomplete 및 요약 관련 메타데이터를 넘기지 않는다. v4의 Memory summarize 지침과 요약 진행 안내를 제거한다.
- load의 state는 constraints/pending_question만 사용한다. complete는 DB의 기존 memory_json에 이 두 필드만 병합한다. legacy summary/summary_sources/hash/claim/watermark는 사용하지 않으며 운영 DB 일괄 삭제 없이 보존한다. jobs의 원본 및 Pin ID/URL/상태를 보존한다.
- 최신 main의 선택적 레퍼런스 갱신에 필요한 previous_result 조회를 유지한다. 이전 보드 원본은 서버 내부에서 재사용하며 prompt_context의 네 필드와 요약 제거 계약은 유지한다.
- 원본 회상은 기존 session/선행 기록/역할/용어/키워드/날짜/ID 필터와 20개 상한·범위 좁히기 안내를 유지한다. 다른 대화/없는 인용/잘못된 출처는 거부한다.
- Spec 및 제거된 요약 전용 테스트를 정리하고 요약 없는 기억의 AC 테스트로 대체한다. 최신 main과 통합한 전체 backend 테스트 결과를 보고한다.
## AC
- Given 긴 대화 또는 legacy 요약 필드, When 요청 처리, Then summarize 호출/등록/실행 및 요약 후보 조회 없이 처리하고 본문/회상 입력에는 요약 필드와 텍스트가 없다.
- Given 체형 조건과 확인 질문, When 포즈만 수정하는 짧은 답변, Then 기존 체형과 질문을 입력에 유지하고 명시한 포즈만 갱신한다.
- Given 40개 선행 기록과 첫 레퍼런스를 묻는 명시적 요청, When 원본 회상, Then 최근 6개 밖의 첫 기록을 조회·인용하며 원본과 저장된 Pin 데이터는 유지된다.
- Given 다른 대화 또는 위조 출처, When 회상/완료 검증, Then 접근/저장을 거부한다.
- Given 서버 시작/종료, When worker 실행, Then 요약 task 없이 Job/lease/MCP 루프를 실행·취소한다.
- Given legacy 요약 데이터와 저장된 조건, When 새 요청 완료, Then 기존 데이터는 일괄 삭제하지 않고 현재 조건/질문만 갱신한다.
- Given 이전 성공 보드와 legacy 요약 데이터, When 맥락 로딩 및 선택적 레퍼런스 갱신, Then previous_result는 유지하고 요약 필드와 oldest_recent는 입력에 포함하지 않는다.
