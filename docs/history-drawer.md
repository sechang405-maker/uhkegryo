# 로고로 여는 대화 기록

좌측 고정 기록 열을 제거하고 기본 닫힘의 왼쪽 모달 서랍으로 전환한다. 데스크톱 헤더와 모바일 상단 로고가 기록 열기 역할을 맡는다. 열린 서랍의 같은 위치 로고와 명시적 닫기 버튼으로 닫는다. 홈은 서랍의 ‘홈 · 용어 그래프’, 신규 대화는 기존 ‘새 세션’으로 접근한다.

`HistoryDrawer`는 native dialog.showModal()로 배경을 inert 상태로 만들고 첫 버튼에 초점을 둔다. Tab/Shift+Tab 순환, Escape, 바깥 포인터 클릭, 닫을 때 호출 로고로 초점 복귀를 지원한다. 서랍만 스크롤하고 body overflow를 복구한다. 180ms 진입 애니메이션은 reduced motion에서 제거한다. 최대 폭은 화면의 90%이며 닫힘 상태에서는 레이아웃 폭을 차지하지 않는다.

기록 선택은 기존 복원 함수를 호출하고 서랍을 닫는다. 현재 기록을 다시 선택해도 닫는다. 데모 기록 선택에서 초안을 지우던 동작을 제거하여 live와 동일하게 보존한다. 선택한 그래프 용어는 기존 부모 상태를 유지한다. 신규 대화/삭제의 기존 데이터 정책과 API, 페이지네이션은 변경하지 않는다. 추가 패키지는 없다.

## 검증

- 프런트 단위 테스트 106개 통과, demo/live production 빌드 통과.
- Chromium live mock: 세 번 반복 열닫기, 양방향 Tab 경계, Escape와 로고 초점 복귀, 바깥 클릭, 명시적 닫기, 21개 세션 페이지네이션, 기록 복원 후 초안과 그래프 선택 유지, 삭제 취소/확인, 신규 세션.
- 360×740 화면의 폭과 reduced motion 확인. 독립 데모에서 실제 touch tap으로 로고·바깥 영역·기록 선택·신규 세션·삭제 취소/확인 검증. API 및 외부 요청 0건, live mock 브라우저 pageerror 0건.
- 로컬 검증은 별도 127.0.0.1:3117 서버만 사용한다. 실제 DB/모델/운영 서비스와 Docker에는 접근하지 않는다.

## 로컬 실행 경로

최신 Git 작업 사본은 `task-2/graph-repo`다. 기존 `task-2/repo`는 별도 사본이므로 기존 실행법으로 열면 옛 UI가 보인다. graph-repo에는 개인 환경파일이 없다. 이번 작업은 환경파일이나 자격증명을 복사하지 않는다.

기존 사본 적용에 필요한 소스 범위는 `frontend/app/page.jsx`, `frontend/app/globals.css`, `frontend/components/TermGraph.jsx`, `frontend/lib/term-graph.mjs`, `frontend/components/HistoryDrawer.jsx` 다섯 개다. 점검 당시 기존 page/CSS는 그래프 도입 전 b521b91과 동일했고 나머지 세 파일은 없었다. package.json과 package-lock.json은 JSON 내용이 동일하다. 소스 충돌 징후는 없지만 기존 사본은 Git 변경 추적이 없어 자동 동기화하지 않았다. 실제 적용 시 이 다섯 파일만 백업 후 복사하고 기존 사본에서 프런트를 다시 빌드해야 한다. 환경파일·데이터·서버 실행 설정은 유지한다.
