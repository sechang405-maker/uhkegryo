# 통합 답변·서버 대화 복원 연결

## Why
후속 요청을 보내는 사용자는 새로고침 후에도 이전 설명과 답변을 이어서 확인해야 한다. 현재 실제 UI는 탭 내 기록만 유지하고 서버는 answer_text를 전달하지 않는다. AC 통과율과 복원 시 메시지 중복 0건을 측정한다.

## Goal
검증된 일반 해석의 통합 답변을 저장·반환하고 쿠키 소유자의 최근 활동 대화 전체 이력을 복원한다. 새 요청은 복원한 session_id를 명시한다. DB migration, 대화 선택/삭제 UI, 운영 배포, 검색 공급자 변경, 실시간 모델 품질 평가는 제외한다.

## What
실제 모드 진입 시 대화 목록의 첫 항목(최근 활동 순)을 열고 이력을 시간순으로 페이지 조회한다. 유효 쿠키가 없거나 미만료 대화가 없으면 빈 화면에서 시작한다. 첫 전송 시 대화를 생성한다. 복원 실패는 안내와 재시도 버튼을 표시하며 복원 전 전송을 차단한다. 다른 대화로 자동 전환하지 않는다.

완료·실패·확인 질문·회상은 기존 상태별 표시를 유지한다. 복원된 모든 진행 중 job의 polling을 재개하고 job_id로 turn을 갱신한다. polling 실패는 해당 turn에 중단 안내를 남긴다. 홈 검색·카테고리 변경은 대화에 영향을 주지 않는다. 실제 기록은 localStorage에 저장하지 않으며 더미 모드는 기존 동작을 유지한다.

## How
- 실제 기록 열기는 선택한 GET /api/jobs/{id}만 credentials include/no-store로 재조회한다. 응답의 job_id·session_id·종결 상태를 대조한 뒤 결과를 표시한다. 더미는 기존 결과를 즉시 연다. 전체 이력 이미지 일괄 조회와 썸네일 영구 저장은 하지 않는다.
- 조회 중에는 결과 영역에 로딩을 표시하고 실패하면 기록 조회 오류와 재시도를 표시한다. 조회 실패를 Pin 삭제/접근 불가 안내로 바꾸지 않는다. 다른 기록·홈·단일 검색·새 제출·unmount는 이전 조회를 취소하며 늦은 응답은 적용하지 않는다. 대화 turn은 변경하지 않는다.
- InterpretationOutput와 AgentResult의 answer_text는 strict 문자열, 최대 4,000자, 기본 빈 문자열이다. 기존 결과/adapter와 호환한다.
- 모든 prompt 버전의 adapter system 규칙에 통합 한국어 답변 생성을 추가한다. 선택 용어의 쉬운 의미·선택 이유·주의점만 설명하고 URL/Pin·검증되지 않은 사실을 만들지 않는다. 확인 질문에는 빈 문자열을 반환한다. schema Skill 예제도 같은 계약으로 맞춘다.
- 활성 카드 입력에는 plain_meaning_ko와 reference_checkpoints_ko를 추가한다. 팀 피드백을 우선하고 없으면 source_answer_draft/look_for를 사용한다. 검색어·URL·Pin은 모델 입력에 추가하지 않는다.
- resolver 검증 후 success/partial_result 조립에만 answer_text를 전달한다. 확인 질문·안전/범위 거절에는 모델 답변을 노출하지 않는다. 원래 job 완료 transaction이 결과를 저장한다. 회상 필드는 별도로 유지한다.
- v4 통합 답변은 쉬운 뜻·입력 근거·카드 관찰 지점을 짧게 안내하며 내부 ID와 선택 알고리즘 설명을 생략한다. 확인 질문은 기존 대화 조건을 변경하지 않는다. 상세 검증은 ambiguity-answer-quality.md를 따른다.
- GET /api/sessions?limit=1 → GET /api/sessions/{id} → GET /api/sessions/{id}/jobs?limit=100&offset=N. 100건 미만까지 이어 조회하고 job_id로 중복 제거한다. 마지막 job은 GET /api/jobs/{id}로 읽어 응답 전용 이미지도 복원한다.
- 401 목록 응답만 미인증 빈 대화로 취급한다. 이후 401/404, 네트워크·잘못된 payload는 복원 실패다. unmount/Strict Mode 재실행 시 AbortController로 이전 결과 적용·요청을 취소한다.
- POST /api/sessions 201로 새 ID 확보 후 POST /api/agent에 request_text와 session_id만 전송한다. 같은 origin, credentials include, no-store 조회를 사용한다. 클라이언트 맥락/요약은 보내지 않는다.
- 진행 turn 전체에 기존 createJobPoller를 사용한다. 실제 진행 turn이 있으면 추가 전송·기록 열기를 막는다. 종결된 turn은 검색 기록에도 반영한다. 답변은 React plain text로 렌더링한다.

## AC
- Given 완료 job 2개 이상 복원, When 마지막이 아닌 기록 열기, Then 선택 job만 재조회하고 정상 응답 썸네일을 표시한다. 더미는 재조회하지 않는다.
- Given 기록 재조회 장애, When 결과 열기, Then 로딩 후 기록 조회 오류·재시도를 표시하고 Pin 상태와 이전 대화를 변경하지 않는다.
- Given 진행 중 기록 조회, When 다른 기록/화면 선택 또는 정리 후 이전 응답 도착, Then 취소된 응답이 현재 결과를 덮어쓰지 않는다.
- Given 일반/부분 결과와 유효 해석, When worker 완료, Then answer_text가 보존되며 이미지 실패에도 사라지지 않는다.
- Given 없는/4,001자/잘못된 타입 답변, When schema 검증, Then 누락은 빈 문자열로 호환하고 길이·타입 오류는 거부한다.
- Given resolver가 확인 질문을 반환, When 조립, Then 모델 answer_text는 노출되지 않는다.
- Given 100건 이상 이력, When 복원, Then 페이지 전체를 시간순으로 표시하고 같은 job을 중복 표시하지 않는다.
- Given 복원된 session_id, When 후속 요청, Then 해당 ID를 명시하고 클라이언트 대화 원문/요약을 전송하지 않는다.
- Given 유효 쿠키 없음/빈 목록, When 진입, Then 빈 대화로 시작하고 첫 전송 시 새 대화를 생성한다.
- Given 이력 401/404 또는 조회 장애, When 복원, Then 전송을 막고 재시도를 제공한다. 실패한 다른 대화로 fallback하지 않는다.
- Given 여러 진행 job, When 복원 후 polling, Then 각각 종결/중단될 때까지 조회하며 turn별 갱신·중단 안내를 보존한다.
- Given 화면 정리/새 복원, When 늦은 응답 도착, Then 취소된 요청을 적용하지 않는다.

기존 studio-conversation-ui.md의 실제 모드 복원 제외 및 studio-persistent-conversation.md의 구현 전 경계는 이 연결 기능에 한해 본 문서로 대체한다. 구현/테스트는 이 문서의 범위만 증명하며 실제 모델 의미 품질·운영 DB 연결은 별도 QA다.

검증: frontend 43 passed (이전 기록 재조회·썸네일 표시·조회 오류·다른 선택/정리 후 늦은 응답 회귀 포함), backend 420 passed / 23 skipped. production build는 기존 dependency를 복사한 임시 검증 디렉터리에서 기본 Turbopack으로 통과했다. 브라우저 검증용 로컬 Next 서버 실행은 자동 승인 검토의 blocked by policy로 거부되어 미실행이다. 실제 PostgreSQL/OpenRouter E2E와 수동 브라우저 QA는 미검증이다.
