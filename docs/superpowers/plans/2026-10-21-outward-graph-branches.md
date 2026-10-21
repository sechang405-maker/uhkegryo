# Outward Graph Branches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arrange expanded 3D graph branches strictly outward inside deterministic category sectors.

**Architecture:** Compute a role-sector axis and radial level in immutable world space, then place sibling fans inside a bounded 3D cone. Keep the existing common camera projection and visible-dot DOM/SVG anchor unchanged.

**Tech Stack:** JavaScript ES modules, React 19, Next.js 16, Node test runner, Playwright/Chrome.

## Global Constraints

- Preserve independent yaw/pitch, perspective, depth, zoom, and immutable world coordinates.
- Do not move nodes individually during camera interaction.
- Preserve AND/OR edges, node deduplication, collapse, selection, search, desktop, and mobile behavior.
- Apply changes only to the user's personal repository and its execution copy.

---

### Task 1: World-space outward sector layout

**Files:**
- Modify: `frontend/tests/term-graph.test.mjs`
- Modify: `frontend/lib/term-graph.mjs`

**Interfaces:**
- Consumes: `buildExpandedTermGraph(baseTerms, catalogTerms, expandedIds)`.
- Produces: the same `{nodes, edges}` shape with deterministic immutable `x`, `y`, `z` anchors.

- [x] **Step 1: Write the failing tests**

Add real-graph and synthetic assertions that every acyclic child has a larger origin radius than its parents, remains inside its category cone, and a grandchild remains farther out than its child.

- [x] **Step 2: Run the focused test and verify RED**

Run: `node --test tests/term-graph.test.mjs`

Expected: outward-radius and category-sector assertions fail against the current full-circle placement.

- [x] **Step 3: Implement the minimal deterministic cone layout**

Add vector helpers, deterministic sibling fan slots, multi-parent direction/radius resolution, and constrained collision spreading. Do not change `projectNode` or `projectGraph`.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `node --test tests/term-graph.test.mjs`

Expected: all graph unit tests pass.

### Task 2: Actual browser and regression verification

**Files:**
- Modify: `frontend/tests/browser/graph-layout.cjs`

**Interfaces:**
- Consumes: rendered `data-world-x/y/z`, relation edges, visible-dot anchors, and keyboard/pointer camera controls.
- Produces: browser evidence for outward placement plus the existing 3D and anchor invariants.

- [x] **Step 1: Add browser assertions**

Expand all currently available roots, then assert outward world radii before and throughout continuous drag while endpoints, expand controls, and labels stay anchored. The current reviewed catalog has no expandable second-level node, so the unit fixture exercises simultaneous body/pose categories and a pose grandchild through the same production layout function.

- [x] **Step 2: Verify the browser test fails before runtime synchronization**

Run the browser script against `http://127.0.0.1:3100` and confirm the old runtime violates outward placement.

- [x] **Step 3: Build and synchronize the implementation**

Copy only changed graph files to the non-Git execution copy, run `npm run build`, and restart port `3100`.

- [x] **Step 4: Run complete verification**

Run `npm test`, production build, graph layout/expand/query browser scripts, hash comparison, and CI for the exact pushed commit.
