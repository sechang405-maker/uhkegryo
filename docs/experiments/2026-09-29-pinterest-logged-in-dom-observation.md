# Pinterest 로그인 DOM 관찰 기록 — 2026-09-29

## 목적

공개 검색 provider가 Pin ID와 원본 URL을 찾을 때 사용할 수 있는, 실제 Pinterest
검색 결과 DOM의 속성명을 확인한다.

## 관찰 조건

- 기존에 로그인된 Chrome의 Pinterest 검색 결과 탭을 읽기 전용으로 확인했다.
- 검색어는 `gesture drawing action line reference drawing`이었다.
- 로그인·쿠키·계정 정보는 입력·추출·저장하거나 서버에 전달하지 않았다.

## 결과

- Pin 카드 컨테이너는 `data-test-id="pin"`과 `data-test-pin-id`를 함께 가졌다.
- 관찰 시점에는 해당 컨테이너와 `/pin/{숫자}/` 링크가 각각 13개였다.
- 앞선 `data-testid="pin"` 선택자는 0개와 일치했다. 실제 속성명은
  `data-test-id`다.
- 카드 순서대로 중복 없는 Pin ID와 원본 URL 8개를 수집할 수 있었다.

## 구현 반영

CDP 진단 경로의 렌더링 대기와 HTML 파서는 아래 선택자를 사용한다. 공개 Chromium
경로는 결과가 없는 검색을 장애로 분류하지 않기 위해 이 선택자를 기다리지 않고 현재
HTML을 parser에 전달한다.

```css
[data-test-id="pin"][data-test-pin-id]
```

이 선택자에서 얻은 ID와 카드 내부 `/pin/{숫자}/` 링크의 ID는 관찰한 8개 결과에서
모두 일치했다.

## 로컬 CDP 통합 실행

- 별도 Chrome 프로필을 `http://127.0.0.1:9222` loopback CDP endpoint로 실행한 뒤,
  사용자가 직접 Pinterest에 로그인했다.
- `PinterestPublicSearchProvider(cdp_endpoint=...)`가 `contrapposto pose`와
  `standing reference` 검색 조각을 받아 실제 로그인 Chrome의 새 임시 탭에서 검색했다.
- 실행 결과는 `role=pose`, `reason_code=null`, 중복 없는 Pin 8개였고, 각 결과의 URL은
  `https://www.pinterest.com/pin/{pin_id}/` 형식으로 정규화됐다.
- 공통 설정 검증을 위해 실행 프로세스에만 더미 `DATABASE_URL`을 주입했다. 이 provider
  호출은 데이터베이스에 연결하지 않았다.

이 결과는 브라우저 내 JavaScript 결과를 Python 파서에 주입한 확인이 아니라, Python
Playwright가 로그인된 Chrome의 CDP endpoint에 연결해 provider 전체 경로를 수행한 결과다.

## 적용 범위와 한계

- 이 기록은 로그인된 개인 브라우저의 DOM 구조를 확인한 진단 결과다.
- 서버의 비로그인 공개 Playwright 환경에서 결과 그리드가 같은 방식으로 렌더링됨을
  보장하지 않는다.
- 로그인 쿠키·계정·OAuth token을 서버 크롤러에 재사용하는 근거가 아니며, 현재
  [Pinterest 공개 검색·Widget 조회 Spec](../specs/pinterest-widget-crawler.md)의
  공개 검색 및 실패 fallback 계약을 바꾸지 않는다.
- 로컬 CDP 경로의 기능 계약과 테스트 범위는
  [Local Pinterest CDP 실험 Spec](../specs/local-pinterest-cdp-experiment.md)을 따른다.
