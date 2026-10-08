# Local Pinterest CDP 실험

## Why

개발자는 로컬에서 이미 로그인한 Chromium 기반 브라우저가 제공하는 Pinterest 검색
DOM이 provider의 Pin ID·URL 파서와 호환되는지 확인해야 한다. 이 경로는 배포
서비스가 아니라 개인 개발 환경의 진단 실험이다.

## Goal

- `cdp_endpoint`가 명시된 provider는 해당 로컬 Chromium에 연결해 임시 검색 탭에서
  최대 8개의 Pin ID와 URL을 수집한다.
- 기본 provider 경로는 기존처럼 새 Chromium을 실행한다.
- 임시 탭은 작업 뒤 닫고, 기존 탭·쿠키·비밀번호·OAuth token은 읽거나 저장하지
  않는다.

Out of scope: 서버 배포, CDP endpoint의 외부 공개, 로그인 자동화, 쿠키 추출·파일
저장·공유, API key 또는 OAuth token 처리.

## What

1. `cdp_endpoint`가 없으면 기존 공개 Chromium loader를 사용해 `domcontentloaded` 뒤
   현재 HTML을 바로 읽는다. 이 경로는 Pin 선택자를 기다리지 않아, Pin이 없는 HTML도
   parser를 거쳐 `PIN_RESULTS_EMPTY`로 분류할 수 있다.
2. `cdp_endpoint`가 있으면 CDP의 기본 browser context에 임시 탭을 열고 검색 URL로
   이동한다.
3. `[data-test-id="pin"][data-test-pin-id]`가 붙을 때까지 기다린 뒤 HTML을 기존
   파서에 전달한다.
4. 연결·페이지 로드·선택자 대기 실패는 provider의 기존
   `PIN_SEARCH_UNAVAILABLE` 결과로 전환한다.

## How

- `PinterestPublicSearchProvider`는 `html_loader` 또는 `cdp_endpoint` 중 하나만
  받는다. 둘 다 지정하면 `ValueError`다.
- CDP endpoint는 로컬 loopback URL만 허용한다.
- CDP 연결은 `playwright.chromium.connect_over_cdp()`를 사용한다.
- provider가 연 임시 Page만 `close()`한다. 연결된 browser는 close하여 연결만
  해제하며, 기존 context·Page를 닫지 않는다.
- 검색 timeout은 기존 15초를 사용한다.

## AC

**AC-01 · 기본 경로 보존**

- GIVEN: `cdp_endpoint`가 없다.
- WHEN: provider가 검색한다.
- THEN: 기존 공개 Chromium loader가 Pin 선택자를 기다리지 않고 현재 HTML을 반환한다.

**AC-02 · CDP 경로**

- GIVEN: loopback `cdp_endpoint`가 지정됐다.
- WHEN: provider가 검색한다.
- THEN: CDP 연결의 기본 context에 새 Page를 열고 렌더링된 Pin 선택자를 기다린다.
- AND THEN: provider가 연 Page만 닫고 browser 연결을 해제한다.

**AC-03 · 안전한 구성**

- GIVEN: `html_loader`와 `cdp_endpoint`가 함께 지정됐다.
- WHEN: provider를 생성한다.
- THEN: `ValueError`를 발생시켜 로그인 DOM source의 우선순위를 모호하게 만들지
  않는다.

**AC-04 · 연결 실패**

- GIVEN: CDP endpoint에 연결할 수 없다.
- WHEN: provider가 검색한다.
- THEN: `PIN_SEARCH_UNAVAILABLE`과 빈 Pin 목록을 반환한다.
