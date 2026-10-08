# Studio 프론트 PR 분리·병합 순서

## Why
원본의 대규모 프론트 변경을 코드 추가+삭제 400줄 이하의 검토 단위로 나눈다.

## Goal
아래 순서로 누적 적용하면 기존 로컬 프론트와 같은 화면·동작을 제공한다. backend와 실제 .env는 제외한다.

## What
| 순서 | 브랜치 | base | 변경 범위 |
| --- | --- | --- | --- |
| 1 | OSC13/feature/studio-data-models | main | 카드·검색어·결과 모델과 fixture |
| 2 | OSC14/feature/studio-base-ui | OSC13/feature/studio-data-models | 기본 브랜드 화면·부채꼴 탐색 |
| 3 | OSC15/feature/studio-gallery-navigation | OSC14/feature/studio-base-ui | 메뉴·갤러리·복사·확대 보기 |
| 4 | OSC16/feature/studio-category-search | OSC15/feature/studio-gallery-navigation | 단일 검색·개별 모드 재검색 |
| 5 | OSC17/feature/studio-conversation-ui | OSC16/feature/studio-category-search | 통합 답변·대화 UI |
| 6 | OSC18/feature/studio-loading-states | OSC17/feature/studio-conversation-ui | 공통 로딩·이미지 대기·접근성 |

## How
Stacked PR이므로 앞 단계가 먼저다. 선행 PR을 병합한 뒤 후속 PR의 base를 main으로 변경하고 diff를 확인한다. squash merge로 부모 commit이 main에 남지 않으면 후속 branch의 해당 단계 commit만 최신 main 위로 rebase해 이전 단계 diff가 다시 나타나지 않게 한다. 전체 stack을 main으로 한 번에 rebase하지 않는다. 실제 강제 push가 필요하면 별도 승인을 받고 force-with-lease를 사용한다. Agent가 자동 승인·병합·auto-merge하지 않는다.

## AC
- Given 각 branch의 직전 base, When diff 확인, Then 코드 추가+삭제가 400줄 이하이다. 테스트도 코드로 센다.
- Given 각 단계, When npm test와 npm run build, Then 통과한다.
- Given 최종 단계, When 원본 프론트와 비교, Then 필요한 코드와 설정 예시가 동일하다.
- Given 모든 PR, When 파일 확인, Then backend와 실제 비밀 환경 파일은 포함하지 않는다.

## 검증과 연결 경계
각 단계에서 로컬 unit test와 production build를 실행했다. 이는 실제 LLM·DB·검색 공급자 E2E 성공을 뜻하지 않는다. 실제 backend 연결은 studio-frontend-handoff.md를 따른다. 기존 UI 검증·실시간 검색 실패 관찰은 원본 작업 폴더에서 수행한 결과이며, 분리된 단계별 UI의 모든 상태를 다시 실행한 것은 아니다.
