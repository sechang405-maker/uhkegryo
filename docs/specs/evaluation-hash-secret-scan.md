# 평가 소스 지문 secret scan 오탐 예외

## Why
- 대상: 평가 실행 소스 지문을 검증하는 리뷰어.
- 상황: 전체 git 이력을 검사하는 gitleaks가 PR #107의 SHA-256 두 건을 generic-api-key로 검출한다.
- 문제: 실제 소스 파일 재현성 근거가 secret으로 오인되어 CI가 실패한다.
- 지표: 해당 두 건만 무시하고 나머지 전체 이력 검사가 통과한다.

## Goal
- 확인된 두 검출 fingerprint만 예외로 등록한다.
- 제외: secret 검사 중단, 파일/디렉터리 전체 제외, 지문 삭제, git 이력 수정.

## What
- 원본 metadata와 SHA-256은 그대로 보존한다.
- 알려진 commit·파일·rule·행 조합 두 건에 한해 무시한다. 다른 commit 또는 행의 검출은 계속 보고한다.

## How
- `.gitleaksignore`에 원본 검출 보고서의 fingerprint 두 개를 기록한다.
- CI는 `--gitleaks-ignore-path /repo/.gitleaksignore`를 명시해 Docker의 실행 디렉터리에 의존하지 않는다.
- `fetch-depth: 0`과 전체 git 이력 스캔을 유지한다. CI와 동일한 Docker image/명령 및 PR merge commit 이력으로 검증한다.
- 별도 임시 clone에서 확인된 지문과 다른 test token 검출이 계속 실패함을 확인한다. test token은 저장소에 커밋하거나 출력하지 않는다.

## AC
- Given 원본 두 소스 지문 검출, When 전체 이력 스캔과 예외 적용, Then 두 건만 제외하고 통과한다.
- Given 같은 metadata의 다른 검출 fingerprint, When 검사, Then 제외되지 않고 실패한다.
- Given 평가 metadata, When 수정 전후 비교, Then 지문·재현성 내용은 동일하다.
