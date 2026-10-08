# Studio 기본 UI와 텀카드 탐색

## Why
그림 초보자가 체형·포즈·시점·투시·구도를 한 화면에서 탐색할 필요가 있다.

## Goal
브랜드 UH, 붉은 테두리, 흰색에서 연분홍으로 이어지는 채팅 배경, 부채꼴 카드, 고정 입력창을 제공한다. 이 단계의 카드 클릭은 선택 표시만 바꾼다.

## What
홈은 실제 모드에서도 검수된 예시 카드를 표시한다. 예시 카탈로그에는 답변·핀 결과가 없으며, 결과 갤러리는 완료된 API 결과만 사용한다. 상세 계약은 studio-home-catalog.md를 따른다. Enter는 제출, Shift+Enter는 줄바꿈이며 IME 조합 중에는 제출하지 않는다.

## How
page.jsx에 기존 agent 요청·job polling을 유지하고 결과 카드 모델을 적용한다. globals.css는 스튜디오 전체 UI의 브랜드 스타일을 정의한다. 메뉴·갤러리·검색·통합 대화 동작은 후속 PR에서 연결한다.

## AC
- Given 카드 결과, When 화면 표시, Then 다섯 카테고리는 부채꼴로 보인다.
- Given 입력 중, When Enter, Then 유효 요청만 제출한다.
- Given IME 조합 또는 Shift+Enter, When Enter, Then 제출하지 않는다.
- Given 긴 채팅, When 데스크톱 화면, Then 입력창은 하단에 유지되고 채팅 영역만 스크롤한다.
- Given 모바일 화면, When 표시, Then 카테고리는 세로 배치된다.
