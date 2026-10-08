# 개인 포트폴리오 배포 — 무료 데모 기본·실제 AI 선택

## Why

- **페르소나**: 팀 프로젝트 종료 후 개인 포트폴리오를 공개하는 팀원과 채용 평가자.
- **상황**: 각자 URL에서 제품 흐름과 구현 역량을 보여주되 공용 GCP 소유자에게 비용을 발생시키지 않는다.
- **문제**: 현재 데모는 development 전용이며 production에서 환경변수만 바꿔 사용할 수 없다. 팀 backend를 공유하면 호출 비용과 유지 책임이 계속 한 사람에게 남는다.
- **측정 지표**: 데모 backend/LLM 호출 0건, 비밀값 포함 0건, 개인 배포의 공용 리소스 참조 0건, 샘플 시나리오 성공률 100%.

## Goal

- 개인 공개의 기본값을 backend 없는 샘플 데모로 정의한다. Vercel 무료 플랜의 허용 용도·사용량 범위 내에서 운영하며 backend·DB·LLM의 실행 비용을 발생시키지 않는다. 모든 상황의 총비용 0원을 보장하지 않는다.
- production build에서도 대표 입력·답변·용어·대화 흐름을 체험하고 모든 화면에 데모임을 명시한다.
- 실제 AI 운영은 운영자가 자기 계정·결제·secret을 준비한 경우에만 선택한다. 팀 공용 리소스를 기본값이나 장애 fallback으로 사용하지 않는다.
- **Out of Scope**: 새로운 AI 기능, 요청 기반 Cloud Run Jobs worker 전환, 신규 과금 차단 기능, 사용자 로그인, 실사용 대화 데이터 이관, Pinterest 이미지 저장·재게시, custom domain 구매, 실제 배포 및 GitHub 변경.

## What

**Happy Path**
1. 개인이 자기 Vercel 프로젝트를 만들고 `NEXT_PUBLIC_UI_DEMO=1`로 배포한다.
2. 방문자는 “샘플 데모 · 실제 AI 및 검색 미연결” 안내와 대표 입력 3개를 본다.
3. 대표 입력을 선택·제출하면 해당 fixture 결과와 용어를 표시한다.
4. 대화 입력, 결과 재열기, 카테고리 탐색을 브라우저 내부에서 수행한다.
5. 실제 서비스를 공개하려는 운영자는 자기 backend·DB·key를 준비하고 `NEXT_PUBLIC_UI_DEMO=0` 및 자기 `AGENT_API_ORIGIN`으로 별도 배포한다.

**Edge Cases**

| 상황 | 처리 방식 |
| --- | --- |
| 대표 입력 외 자유 입력 | 입력 길이는 기존 검증을 적용하고 “샘플에 없는 입력입니다. 대표 예시를 선택해 주세요.”를 표시한다. 임의 해석 결과를 생성하지 않는다. |
| 데모 모드에서 공용 API origin이 남음 | rewrite를 생성하지 않고 외부 호출을 차단한다. 배포 검사에서 설정 잔존을 지적하고 제거한다. |
| mode 누락·오타 | production build 검사를 실패시킨다. 명시적 `1` 또는 `0`만 허용한다. 로컬 개발 기존 기본 동작은 유지한다. |
| localStorage 불가·손상 | 메모리 상태로 계속 동작하며 저장 실패를 안내한다. backend 저장으로 전환하지 않는다. |
| 새로고침·다른 기기 접속 | 동일 브라우저의 데모 텍스트 이력만 복원한다. 기기 간 동기화·서버 세션을 제공하지 않는다. |
| 검색·스케치·카테고리 변형 선택 | 준비한 용어 fixture 또는 “데모에서는 실시간 검색을 제공하지 않습니다.” 안내를 표시한다. API를 호출하지 않는다. |
| 실제 AI 배포 주소 누락·팀 주소 사용 | 배포 사전 검사를 실패시킨다. 자기 리소스 소유권·결제 계정 확인 없이는 live 배포를 승인하지 않는다. |
| live 장애 | 기존 live 오류 안내를 표시한다. 데모 답변으로 조용히 대체하지 않는다. |

## How

### 모드와 Vercel 설정

- `NEXT_PUBLIC_UI_DEMO`를 유일한 모드 선택자로 유지한다. `1`은 production에서도 데모, `0`은 실제 API 연결이다. build 시 결정하며 변경 시 재배포한다. 방문자가 UI에서 live 모드를 켜는 기능은 만들지 않는다.
- 현재 `frontend/lib/demo-job.mjs`의 development 제한은 후속 구현에서 변경한다. 기존 더미 Pin 이미지와 답변을 공개 데모에 그대로 사용하지 않는다.
- Next.js, Root Directory `frontend`, `npm ci`, `npm run build`, Node.js 22.x와 root 외부 파일 포함 설정은 팀 배포 Spec을 따른다.
- demo 프로젝트에는 `AGENT_API_ORIGIN`과 backend secret을 설정하지 않는다. `NEXT_PUBLIC_API_BASE_URL=/api`는 호환을 위해 유지하되 호출하지 않는다.
- `frontend/next.config.mjs`는 demo build에서 API rewrite를 반환하지 않는다. live build에서는 팀 Spec의 기존 rewrite를 유지한다. demo에서 `/api/*` 직접 요청은 backend로 전달되지 않고 404로 종료된다.
- 초기 대화 복원·새 대화·입력 제출·polling·이력 조회·용어 검색·검색 변형까지 모든 경로를 데모 adapter로 처리한다. 서버·클라이언트 모두 FastAPI/MCP/SearXNG/Langfuse/LLM에 요청하지 않는다.

### 샘플 데이터와 표시

- `frontend/lib/portfolio-demo-fixtures.mjs`에 팀이 작성한 공개 예시 3건을 둔다. 기존 result schema를 유지하고 안정적인 `demo-` ID와 카탈로그에 존재하는 term_id만 사용한다.
- 대표 입력은 “어깨와 골반 폭이 비슷하고 허리가 들어간 캐릭터”, “한쪽 다리에 체중을 싣고 선 캐릭터”, “아래에서 올려다보는 앉은 캐릭터”로 고정한다. 각 답변은 해당 체형·포즈·시점 조건만 설명하며 실제 AI 생성이라고 표시하지 않는다.
- 검색을 실행하지 않으므로 각 term의 `pins`는 빈 배열이다. 갤러리는 “데모에서는 실시간 이미지 검색을 제공하지 않습니다.”를 표시한다. 썸네일 URL·이미지 바이트·실사용 trace를 fixture에 포함하지 않는다.
- 대표 입력 매칭은 앞뒤 공백 제거 후 정확히 일치할 때만 수행한다. 등록되지 않은 입력은 안내만 표시하고 성공 답변 이력으로 저장하지 않는다.
- 데모 배지를 홈·대화·결과에 항상 표시한다. 제출 결과는 즉시 로컬 completed로 표시하며 실제 queue·LLM 진행 단계를 흉내 내지 않는다.
- 기존 데모 전용 localStorage를 재사용하되 fixture ID, 입력 텍스트와 답변 텍스트만 최대 50개 저장한다. 실제 세션 쿠키를 발급하지 않는다. 손상 데이터는 무시하고 초기 샘플로 복구한다.
- 방문자 입력은 backend·분석·trace로 전송하지 않는다. 외부 영상·소스 링크를 추가하는 작업은 별도 요청 범위로 둔다.

### 개인별 실제 AI 선택 배포

- 선택한 개인만 [팀 운영 배포](./vercel-deployment.md)의 live 실행·AC 계약을 자기 리소스에 적용한다. 상시 worker 비용과 종료 책임은 해당 개인에게 있다.
- 각자 자기 결제 계정에 연결된 GCP project, API/MCP 서비스 계정, Secret Manager, Neon project/DB, OpenRouter key, 필요한 검색·Langfuse 서비스를 준비한다. 팀 소유자의 결제 계정 연결·secret 복사·공용 backend 호출은 허용하지 않는다.
- 배포 기록에 리소스 소유자·결제 계정·운영 종료일·예산과 secret 참조를 남긴다. 비밀값 원문을 기록하지 않는다.
- 이 Spec은 상시 비용을 줄이기 위한 Cloud Run Jobs 변환을 구현하지 않는다. 그 방식은 별도 worker 실행 Spec과 구현·AC가 필요하다.
- 팀 종료 정리는 팀 Spec을 따른다. 개인 무료 데모 전환만으로 기존 GCP 리소스가 종료되는 것은 아니다.

### 변경 범위와 검증

- 후속 구현은 `frontend/lib/demo-job.mjs`, 새 fixture/adapter, `frontend/app/page.jsx`와 관련 표시 컴포넌트, `frontend/next.config.mjs`, `.env.example`의 모드 설명 및 관련 frontend 테스트로 제한한다. backend 동작은 변경하지 않는다.
- 같은 기능의 구현과 문서는 함께 갱신하고 코드 변경 400줄 초과 시 fixture/adapter와 UI 연결을 독립 검토 범위로 나눈다.
- `npm test`, demo/live 각각의 production build, demo production 서버의 전체 사용자 흐름 네트워크 검사로 검증한다. fixture schema·입력 매칭·secret/공용 주소 검사·live 회귀를 포함한다.
- 아래 AC는 후속 구현의 통과 기준이며 현재 통과 결과가 아니다.

## AC (Given-When-Then)

- **AC-01 · production 데모** — Given `NEXT_PUBLIC_UI_DEMO=1`이고 backend 없는 환경, When production build와 서버를 실행, Then 홈·대화·결과를 사용할 수 있고 데모 안내를 항상 표시한다.
- **AC-02 · 대표 입력** — Given 공개 fixture 3건, When 각각의 대표 입력을 제출, Then 해당 샘플 답변·카탈로그 term을 표시하고 pins는 빈 배열이며 API 요청은 0건이다.
- **AC-03 · 자유 입력** — Given 등록되지 않은 유효 입력, When 제출, Then 대표 예시 선택 안내를 표시하고 AI 답변·실제 job·성공 이력을 만들지 않는다. 길이 오류는 기존 검증을 따른다.
- **AC-04 · 모든 호출 차단** — Given demo production 서버, When 초기 로드·대화·카테고리·검색 변형·이력·새로고침을 수행, Then backend/LLM/MCP/SearXNG/Langfuse 호출은 서버와 브라우저 모두 0건이다. `/api/*` 직접 요청도 외부 전달 없이 404다.
- **AC-05 · 저장 경계** — Given 샘플 대화 이력, When 저장과 복원을 수행, Then 데모 ID·입력·답변 텍스트 최대 50개만 유지하고 Pin URL/썸네일·실제 세션·secret을 저장하지 않는다.
- **AC-06 · 저장 장애** — Given localStorage 거부 또는 손상 데이터, When demo를 열고 대표 입력을 제출, Then 메모리 상태로 정상 동작하고 손상 데이터는 복구하며 backend 요청은 없다.
- **AC-07 · 모드 검사** — Given production 환경의 누락/잘못된 모드 또는 live의 누락된 origin, When build 사전 검사를 실행, Then 실패한다. 유효 demo/live build와 기존 live 회귀 테스트는 통과한다.
- **AC-08 · 개인 소유권** — Given 개인 live 배포 신청, When 리소스와 결제 계정을 검토, Then 모두 개인 소유이며 공용 리소스 참조·공용 secret이 0건이다. 확인할 수 없으면 live 배포를 승인하지 않는다.
- **AC-09 · 종료 후 독립성** — Given 팀 backend가 중단된 환경, When 개인 데모의 모든 대표 흐름을 실행, Then 기능이 동작하고 팀 비용을 발생시키는 요청이 0건이다.
- **AC-10 · 정직한 결과 표시** — Given demo 또는 live 장애, When 결과 화면을 표시, Then demo는 샘플임을 명시하고 live 장애는 실제 오류 안내를 유지하며 샘플 성공으로 대체하지 않는다.
