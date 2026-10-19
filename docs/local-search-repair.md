# 로컬 핀 썸네일 복구 (2026-10-19)

## 원인과 처리

실행 스크립트의 기본 검색 컨테이너가 이전 작업 사본의 `pr106-local-searxng-1`이었다. 이 컨테이너는 저장소의 Pinterest URL 패치 없이 원문 링크를 반환했다. 일반 용어 검색 원본 18개 모두 외부 원문 URL이어서 숫자 Pin ID 검증에서 제외됐다. 엔진을 패치한 뒤에는 Pinterest 주소가 반환됐지만 현재 공개 검색의 ID는 `e1_…` 형태였다. 기존 Widget API는 이 ID에 HTTP 400을 반환했다. 두 문제가 겹쳐 있었다.

검색 엔진은 저장소의 고정 기반 이미지와 기존 URL 패치로 빌드했다. parser는 숫자 ID 및 길이 제한이 있는 `e1_` 공개 ID만 허용한다. 숫자 ID는 기존 Widget 조회를 유지한다. 공개 ID는 검색 응답에 포함된 HTTPS `i.pinimg.com` 이미지로 표시하며 사용자정보·임의 호스트·포트·공백·과도한 길이를 거부한다. 인증을 추가하거나 제한을 우회하지 않는다. 공개 CDN URL만 기존 60초/256개 메모리 캐시에 넣고 DB에는 저장하지 않는다. 공개 ID의 과거 결과는 캐시 만료/재시작 후 재검색이 필요할 수 있으며 이 상태를 삭제된 핀으로 오인하지 않는다.

원본 결과가 있는데 유효한 Pin URL이 전혀 없으면 `PIN_SEARCH_UNAVAILABLE`로 구분한다. 실제 빈 결과나 이미 본 Pin 제외로 비는 경우는 기존 `PIN_RESULTS_EMPTY`를 유지한다.

## 실제 실행과 검증

- 사용자 승인으로 기존 검색 컨테이너만 중지·보관하고 `uhkegryo-local-searxng` 하나를 `127.0.0.1:8080`에 실행했다. 이미지 태그는 `uhkegryo/searxng:pin-url-fixed`다.
- 기존 검색 인증값을 새로 만들지 않고 프로세스 메모리로 재사용했다. 기존 settings.yml을 같은 읽기 전용 마운트로 사용하므로 이전 작업 사본의 설정 경로에 대한 의존성은 남아 있다. 다른 프로젝트 컨테이너·기존 이미지·볼륨·DB 데이터는 수정하거나 삭제하지 않았다.
- start-local.ps1의 기본 컨테이너명을 전용 이름으로 바꿨다. URL과 프런트 포트는 그대로다. 실제 앱 repo에 변경 코드를 백업·동기화하고 API만 재시작했다.
- 실제 localhost3100 브라우저에서 검수된 역삼각형 직접 검색 → Pin 8개, available 8개, reason 없음 → CDN 이미지 HTTP200 8개와 naturalWidth/naturalHeight 양수 확인. 페이지 오류 0. 세션/프로필 쓰기는 브라우저에서 차단하고 LLM/생성 API를 호출하지 않았다.
- 전체 백엔드 811 passed / 38 skipped, 프런트 106 passed. 기존 FastAPI/SQLite 테스트 경고 4개. Docker 패치 이미지 빌드 성공. 프런트 코드는 변경하지 않아 실행 중인 검증된 production 빌드를 유지한다.
- 같은 `docker stats --no-stream` 방식의 검색 종료 후 순간값: 기존 117.5MiB / CPU0.20% / PIDS8, 교체 후 104.4MiB / CPU0.21% / PIDS8. 동시 실행은 하지 않는다. 동일한 통제 부하 실험이 아니므로 성능 개선률이나 최대 메모리를 뜻하지 않는다.

## 기존 컨테이너 연결과 시작 경위

Compose 프로젝트 `pr106-local`, 작업 경로 `C:/Users/user/Documents/Codex/2026-09-14/so`, compose 파일 `local-pr106-compose.yaml`. 파일의 API build 경로와 검색 설정 마운트는 `C:/Users/user/Documents/Codex/worktrees/proj2-4-studio-pr-stack`를 가리킨다. 그 사본의 frontend package 이름이 `uhkegryo-frontend`여서 별개 제품이 아닌 같은 어케그려의 이전 작업 사본임을 확인했다.

기존 검색은 `practice_default` 네트워크에서 practice Langfuse/DB/Redis/MinIO/ClickHouse와 함께 연결되어 있었다. 네트워크 공유만으로 이 서비스들이 검색을 사용했다고 판단할 수 없다. 이전 `pr106-local-api-1`은 중지 상태였고, 이번 어케그려 API가 명시적으로 localhost8080을 사용한 것은 확인됐다. 기존 설정 마운트 외에 `/etc/searxng` 및 `/var/cache/searxng` 익명 볼륨이 있으며 그대로 보관한다.

생성 시각은 2026-10-02T05:44:26Z, 이번 시작 시각은 2026-10-19T00:57:59Z, 재시작 정책은 `no`였다. 이번 어케그려 실행 요청에서 에이전트가 기존 start-local.ps1을 실행했고, 그 기본값이 구형 컨테이너를 선택해 시작했다. API 실행 로그 `api-20261019-095802-297.out.log`의 시각과 일치한다. Docker 자동 재시작 때문이라고 추측하지 않는다.

## 복구 방법

필요 시 전용 검색만 `docker stop uhkegryo-local-searxng`으로 중지하고 `docker start pr106-local-searxng-1`로 원래 컨테이너를 다시 시작할 수 있다. 동일한 localhost8080을 쓰므로 동시에 시작하지 않는다. 이후 실행 스크립트는 `-SearchContainer pr106-local-searxng-1`을 명시한다. 이는 구형 엔진의 원래 URL 문제도 되돌리므로 현재 정상 구성에서는 실행하지 않는다. DB·볼륨 삭제나 초기화는 필요 없다.
