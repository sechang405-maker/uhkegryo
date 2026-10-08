# 실제 모드 홈 텀카드 탐색

## Why
더미 모드를 끄면 검색 전 job=null이라 부채꼴이 사라진다. 홈 예시 탐색은 검색 결과가 없어도 제공해야 한다.

## Goal
실제 모드의 홈에 기존 검수된 예시 카드 14개를 다섯 카테고리로 표시한다. 더미 답변·이미지·기록을 실제 모드에 넣지 않는다.

## What
홈 부채꼴은 고정된 검수 카탈로그를, 갤러리는 완료된 서버 결과 또는 단일 검색 응답을 사용한다. 홈 카드는 예시라고 표시하고 term_id로 기존 term-search를 호출한다. 백엔드 실패는 기존 안내를 유지한다.

## How
home-catalog.mjs가 기존 14개 카드의 ID·역할·피드백·고정 검색어를 구성한다. runtime_eligible 및 active_in_current_contract를 확인하며 pins는 빈 배열이다. demo-job.mjs는 같은 카드에 개발용 더미 핀만 붙인다. page.jsx의 홈 슬롯과 결과 슬롯을 분리한다. backend와 환경변수는 변경하지 않는다.

## AC
- Given 더미 모드 꺼짐 및 검색 전, When 홈 표시, Then 5개 카테고리의 부채꼴과 UH 아이콘이 보이고 대화는 비어 있다.
- Given 홈 예시, When 카드 클릭, Then 기존 term-search로 해당 ID를 보내며 대화·검색 기록을 생성하지 않는다.
- Given 서버 결과, When 결과 표시, Then 홈의 예시 핀이나 답변을 섞지 않는다.
- Given 완료 결과 또는 검색 실패, When 홈으로 이동, Then 기존 예시 카드를 다시 표시한다.
- Given 개발 더미 켜짐, When 카드 탐색, Then 기존 미리보기 기능을 유지한다.

## 작업 계획
1. demo-job.test.mjs에 홈 카탈로그 표시·빈 핀·검수 상태 테스트 추가 후 실패 확인.
2. 카탈로그 구성 코드를 home-catalog.mjs로 분리하고 demo-job.mjs가 재사용하도록 수정.
3. page.jsx의 홈 슬롯을 HOME_TERMS로, 갤러리는 기존 job 결과로 유지.
4. npm test, npm run build, git diff --check 및 실제 모드 브라우저 확인. 커밋·push·PR은 별도 승인 전 하지 않는다.

## 검증 기록
- 2026-10-02: 회귀 테스트 2개를 포함한 39개 테스트, production build, git diff --check 통과.
- 더미 모드를 끈 브라우저에서 다섯 카테고리·14개 카드와 빈 대화를 확인했다. 1280×850 화면에서 부채꼴을 확인하고 viewport는 원래 크기로 복원했다.
- 백엔드 실행·유료 LLM·실제 검색·DB 쓰기는 실행하지 않았다. term-search 미구현과 서버 대화 연결은 이번 수정 범위 밖이다.
