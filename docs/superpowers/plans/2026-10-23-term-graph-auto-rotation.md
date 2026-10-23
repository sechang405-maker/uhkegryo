# 3D Graph Auto Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 3D 그래프가 120초 주기로 자동 회전하고 실제 수동 회전이 시작되면 해당 마운트 동안 중지되게 한다.

**Architecture:** 프레임 시간 계산은 `term-graph-auto-rotation.mjs`의 순수 상태 함수가 담당한다. `TermGraph.jsx`는 기존 RAF 루프에서 이 함수를 호출해 yaw만 갱신하고, 기존 5px 드래그 임계값을 넘는 순간 상태를 중지한다.

**Tech Stack:** React, requestAnimationFrame, Node test runner, Next.js 16.4.1

## Global Constraints

- 한 바퀴 기본 주기는 120초다.
- 기존 RAF 루프를 재사용하며 별도 루프를 만들지 않는다.
- 월드 좌표, 노드·엣지 배치, 카메라 pitch/zoom, 클릭 임계값은 변경하지 않는다.
- reduced-motion과 비활성 탭에서는 자동 회전하지 않는다.
- 브라우저 자동화는 사용하지 않는다.

---

### Task 1: 프레임 시간 기반 자동 회전 상태

**Files:**
- Create: `frontend/lib/term-graph-auto-rotation.mjs`
- Create: `frontend/tests/term-graph-auto-rotation.test.mjs`

**Interfaces:**
- Produces: `createAutoRotationState()`, `advanceAutoRotation(state, now, enabled)`, `stopAutoRotation(state)`

- [ ] **Step 1: 120초 주기, 비활성 pause, 큰 delta 제한, 중지 영속성 테스트를 작성한다.**
- [ ] **Step 2: `node --test tests/term-graph-auto-rotation.test.mjs`로 함수 부재 RED를 확인한다.**
- [ ] **Step 3: 최대 프레임 delta 50ms와 `2π / 120000ms` 속도의 순수 상태 함수를 구현한다.**
- [ ] **Step 4: 같은 명령으로 GREEN을 확인한다.**

### Task 2: 기존 그래프 RAF와 포인터 제스처 통합

**Files:**
- Modify: `frontend/components/TermGraph.jsx`
- Modify: `frontend/tests/term-graph-motion.test.mjs`

**Interfaces:**
- Consumes: Task 1 자동 회전 상태 함수
- Produces: 단일 RAF에서 펼침 모션과 자동 yaw가 함께 갱신되는 `TermGraph`

- [ ] **Step 1: 소스 연결 테스트에 단일 RAF, 드래그 임계값 이후 중지, reduced-motion/visibility 조건과 cleanup 기대를 추가한다.**
- [ ] **Step 2: 테스트가 새 연결 부재로 실패하는지 확인한다.**
- [ ] **Step 3: 기존 effect를 `hasMotion || autoRotation` 조건으로 확장하고, pointer move가 5px를 넘거나 pinch를 시작할 때 `stopAutoRotation`을 호출한다.**
- [ ] **Step 4: 노드 확장과 재렌더가 중지 상태를 초기화하지 않는지 표적 테스트로 확인한다.**

### Task 3: 회귀, 반영, 실행본 확인

**Files:**
- Verify: `frontend/tests/*.test.mjs`
- Verify: `frontend/.next`

- [ ] **Step 1: 자동 회전 및 기존 그래프 모션 테스트를 실행한다.**
- [ ] **Step 2: 프런트 전체 테스트와 `npm run build`를 실행한다.**
- [ ] **Step 3: 명령 단위 무서명 커밋 후 개인 `main`에 푸시한다.**
- [ ] **Step 4: 실제 실행본에 변경 파일만 동기화하고 3100을 재빌드·재시작한다.**
- [ ] **Step 5: 제공 번들 마커, HTTP 200, 정확한 SHA CI를 확인한다.**
