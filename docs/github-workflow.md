# GitHub 운영 계획

## 1. 운영 목적

이 저장소를 단순한 코드 저장 공간이 아니라, 팀의 개발 과정과 협업 기록을 확인할 수 있는 프로젝트 저장소로 운영합니다.

이번 문서는 기존 저장소 협업 규칙을 반복하지 않고, 우리 팀이 추가로 정한 **개인 식별용 이니셜과 브랜치 번호 규칙**을 정의합니다.

## 2. 팀원 식별자

| 팀원   | 이니셜 |
| ------ | ------ |
| 김호섭 | `KHS`  |
| 윤태현 | `YTH`  |
| 오세창 | `OSC`  |

팀원은 모두 프로젝트 참여자로 관리하며, 이니셜은 브랜치 이름에서 작업자를 식별하는 용도로 사용합니다.

## 3. 브랜치 이름 규칙

```text
{이니셜}{개인 브랜치 번호}/{작업 유형}/{작업 내용}
```

예시:

```text
KHS01/docs/readme
OSC01/feature/model-training
YTH01/feature/stt-pipeline
YTH01/feature/streamlit-ui
OSC01/test/model-evaluation
```

### 3-1. 개인 브랜치 번호

- 각 팀원은 `01`부터 번호를 시작합니다.
- 새 브랜치를 만들 때마다 본인의 번호를 1씩 증가시킵니다.
- 브랜치를 merge하거나 삭제한 뒤에도 사용한 번호를 다시 사용하지 않습니다.
- 번호는 팀원별로 독립적으로 관리합니다.

예시:

```text
KHS01/docs/readme
KHS02/docs/github-workflow
KHS03/fix/streamlit-upload
```

### 3-2. 작업 유형

| 작업 유형  | 용도        | 예시                             |
| ---------- | ----------- | -------------------------------- |
| `feature`  | 기능 추가   | `YTH01/feature/model-training`   |
| `fix`      | 오류 수정   | `OSC02/fix/upload-error`         |
| `refactor` | 구조 개선   | `KHS02/refactor/pipeline-module` |
| `docs`     | 문서 수정   | `KHS01/docs/readme`              |
| `test`     | 테스트·평가 | `YTH01/test/model-evaluation`    |

작업 내용은 짧고 구체적인 영문 소문자로 작성합니다. 공백 대신 하이픈을 사용합니다.

## 4. 작업 흐름

브랜치를 생성하기 전에는 반드시 최신 `main`을 기준으로 작업해야 합니다. 아래 순서를 생략하거나 다른 브랜치에서 새 브랜치를 분기해서는 안 됩니다.

1. `main` 브랜치로 이동합니다.
2. `origin/main`의 최신 변경사항을 fast-forward 방식으로 반영합니다.
3. 최신화된 `main`에서 새 작업 브랜치를 생성합니다.

```text
작업 내용 확인
    ↓
main 브랜치 이동 및 origin/main 최신화
    ↓
개인 번호를 증가시킨 브랜치 생성
    ↓
작업 단위로 Commit
    ↓
원격 Branch Push
    ↓
Pull Request 생성
    ↓
팀원 Review
    ↓
승인 후 Merge
```

브랜치 생성 예시:

```bash
git switch main
git pull --ff-only origin main
git switch -c KHS02/docs/github-workflow
```

위 순서는 필수입니다. `main`을 최신화하지 않았거나 `main`이 아닌 브랜치에서 분기한 브랜치는 작업 브랜치로 사용하지 않습니다.

커밋 및 push 예시:

```bash
git add docs/github-workflow.md
git commit -m "docs: GitHub 운영 계획 추가"
git push -u origin KHS02/docs/github-workflow
```

세부적인 main 보호, PR 승인, 시크릿, 충돌 해결 규칙은 저장소의 [README.md](../README.md)를 따릅니다.

## 5. 브랜치 점검 체크리스트

- 브랜치를 생성하기 전에 `main`으로 이동했는가?
- 브랜치 생성 직전에 `git pull --ff-only origin main`으로 `main`을 최신화했는가?
- 최신화된 `main`에서 작업 브랜치를 분기했는가?
- 브랜치가 본인의 이니셜로 시작하는가?
- 개인 브랜치 번호가 이전 사용 번호와 중복되지 않는가?
- 작업 유형이 `feature`, `fix`, `refactor`, `docs`, `test` 중 하나인가?
- 작업 내용이 브랜치 이름만으로 이해되는가?
- 한 브랜치에 하나의 작업 목적만 포함되어 있는가?
- 작업 완료 후 PR과 Review 기록이 남아 있는가?
