# Pinterest 즉시 검색

## Why
사용자가 현재 TERM_CARD 검색어를 복사해 Pinterest에 입력하는 단계를 줄인다.

## Goal
상단 즉시 검색을 누르면 표시 중인 검색어의 Pinterest 결과를 새 탭으로 연다.

## What
외부 링크 표시는 “Pinterest ↗”으로 명명하고 접근성 이름은 “Pinterest에서 검색”을 유지한다. 검색어 표시와 복사는 유지한다.
즉시 검색·검색어·복사는 각각 독립된 테두리와 모서리를 가지며 10px 간격으로 배치한다.
즉시 검색에 마우스를 올리거나 키보드 포커스를 두면 브랜드 붉은 테두리·연한 분홍 배경의 툴팁으로 “Pinterest 검색 결과는 계정, 이용 기록 등에 따라 달라질 수 있습니다.”를 표시한다.
카테고리 스크롤 또는 홈 카드 선택으로 검색어가 바뀌면 링크도 함께 변경한다.
복사 성공 시 버튼은 “복사 됨”을 3초 표시하고 “복사”로 돌아온다. 다시 누르면 복사하고 표시 시간을 다시 시작한다.

## How
현재 recommendedSearchQuery를 URLSearchParams로 인코딩하여
https://kr.pinterest.com/search/pins/?q=... 링크를 만든다.
target=_blank, rel=noopener noreferrer를 적용한다. 검색어가 없으면 표시하지 않는다.

## AC
- Given 현재 검색어, When 즉시 검색 선택, Then 해당 검색어의 Pinterest 검색 URL을 새 탭으로 연다.
- Given 카테고리 변경, When 상단 검색어 변경, Then 링크의 q도 같은 검색어가 된다.
- Given 검색어 표시, When 복사 선택, Then 기존 복사 동작을 유지한다.
- Given 복사 성공, When 3초 경과, Then 버튼이 “복사”로 돌아오고 다시 복사할 수 있다.
