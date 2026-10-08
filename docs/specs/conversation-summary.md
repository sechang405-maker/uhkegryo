# 긴 대화 요약
## Why
대화가 길어져도 입력 크기를 제한하면서 오래된 기록을 찾아야 한다.
## Goal
최근 6개 job 외 기록을 순서대로 2,000자 이하 요약에 반영하고 원본은 보존한다. 한 background 실행의 요약은 최대 2배치·30초다.
## What
현재 조건·미해결 질문은 요약과 별도다. 요약은 탐색용이며 회상 답변의 독립 근거가 아니다. 요약은 답변과 분리하고 실패는 별도 worker에서 재개한다.
## How
별도 worker 실행 시 최신 저장된 watermark 이후, 최근 6개를 제외한 선행 종결 job을 6개씩 요약한다. 요약 출력은 text<=2000, source_job_ids<=20이며 입력된 출처만 허용한다. 각 배치의 마지막 (created_at,job_id)를 watermark로 사용한다.
2배치 또는 30초 예산에 도달하면 남은 기록은 다음 background 실행에서 이어 요약한다. 맥락에 `summary_incomplete=true`를 전달하여 요약이 전체 과거를 포함한다고 주장하지 않는다. 회상은 요약 여부와 관계없이 원본 job을 조회한다. 요약 시간 초과는 답변 job 상태를 바꾸지 않는다.
요약 성공 시 요약 필드만 저장하며 조건/질문은 보존한다. 실패 시 기존 저장 요약·watermark를 보존한다.
한 record 정제 문자열은 최대 4,000자, 최근 기록은 최대6개다. 기존 adapter/설정을 사용하되 요약 실패는 별도 루프에서 재개한다. 원문/Pins를 일반 로그에 남기지 않는다.
## AC
- Given 8개 선행 기록, When background 실행, Then 오래된2개는 요약하고 최근6개는 유지한다.
- Given 요약 완료, When 기록 조회, Then 원문은 전부 남는다.
- Given 요약 모델 실패/잘못된 출처/길이 초과, When background 실행, Then watermark를 변경하지 않고 이후 재개한다.
- Given 100개 이상의 선행 job, When 두 background 실행, Then 각 실행은 최대 2회·30초만 요약하고 남은 watermark를 다음 background 실행에서 이어가며 미완료 표시를 전달한다.

답변 경로 분리·중복 실행 방지·저장은 [conversation-summary-background.md](conversation-summary-background.md)를 따른다.
