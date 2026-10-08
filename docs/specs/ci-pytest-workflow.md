# CI pytest workflow

## Why

- **페르소나**: 저장소에 기능을 기여하는 개발자
- **상황**: PR과 main push에서 변경 사항을 자동 검사한다.
- **문제**: 현재 CI는 secret scan만 수행하고 Python 테스트를 실행하지 않아 회귀를 병합 전에 발견하지 못한다.
- **측정 지표**: PR 및 main push마다 backend pytest 실행 결과 확인 가능

## Goal

- **해결 목표**: GitHub Actions에서 backend 테스트를 자동 실행한다.
- **성공 기준**: pull request와 main push 이벤트에서 `backend/tests`의 pytest 결과가 workflow 결과에 반영된다.
- **Out of Scope**: 전체 Python 의존성 고정, 테스트 코드 변경, 배포나 커버리지 업로드

## What

**Happy Path**
1. PR 또는 main push 이벤트가 발생한다.
2. GitHub Actions가 저장소를 checkout하고 Python 런타임을 준비한다.
3. `backend/requirements.txt`를 설치한다.
4. 저장소 루트에서 `searxng/`의 patched SearXNG Docker image를 빌드한다.
5. `backend/tests`를 대상으로 `pytest`를 실행한다.
6. 이미지 빌드 또는 테스트 실패는 workflow 실패로 표시한다.

**Edge Cases**

| # | 상황 | 처리 방식 |
|---|---|---|
| EC-01 | 테스트 실패 | pytest 종료 코드에 따라 job 실패 |
| EC-02 | 의존성 설치 실패 | job 실패로 표시 |
| EC-03 | 대상 테스트가 없음 | pytest 기본 동작에 따라 실패 코드로 표시 |
| EC-04 | pull_request 이벤트 | push와 동일하게 테스트 실행 |
| EC-05 | main push 이벤트 | pull_request와 동일하게 테스트 실행 |

## How

- 새 workflow: `.github/workflows/pytest.yml`
- 트리거: `pull_request` 및 `push` 중 `main` 브랜치
- Runner: `ubuntu-latest`
- Python: 3.12
- 설치 명령: `python -m pip install -r backend/requirements.txt`
- SearXNG image 빌드: `docker build --tag proj2-4/searxng:ci ./searxng`
- 실행 명령: 저장소 루트에서 `python -m pytest backend/tests`
- 기존 secret scan workflow는 변경하지 않는다.

## AC (Given-When-Then)

**AC-01 · PR에서 backend 테스트 실행**
- GIVEN: 유효한 pull request 이벤트가 있다.
- WHEN: pytest workflow가 실행된다.
- THEN: backend requirements 설치 후 `backend/tests` 테스트가 실행되고 종료 결과가 job에 반영된다.

**AC-02 · main push에서 backend 테스트 실행**
- GIVEN: main 브랜치에 push 이벤트가 있다.
- WHEN: pytest workflow가 실행된다.
- THEN: backend requirements 설치 후 `backend/tests` 테스트가 실행되고 종료 결과가 job에 반영된다.

**AC-03 · 테스트 실패 전파**
- GIVEN: backend pytest 테스트가 실패한다.
- WHEN: pytest workflow가 실행된다.
- THEN: pytest step 및 job이 실패한다.

**AC-04 · 패치된 SearXNG 이미지 빌드**
- GIVEN: pull request 또는 main push workflow가 실행된다.
- WHEN: pytest job이 SearXNG image를 빌드한다.
- THEN: `searxng/Dockerfile`의 고정 베이스 이미지에서 Pinterest 엔진 패치를 적용하고, 빌드 실패는 job 실패로 표시한다.
