# Main footer cleanup implementation plan

**Goal:** Apply the six approved UI reductions while preserving selection, search and accessible graph controls.

**Architecture:** Use native details/summary for graph controls and help. Keep graph geometry and gestures unchanged. Move the existing storage notice into the history drawer; use CSS focus/media conditions for the keyboard hint and show the character counter from 450 characters.

**Tech Stack:** Next.js, React, CSS, Node tests and Playwright browser checks.

## Constraints

- Only the approved six UI changes; retain list view, mobile pinch, drag, native wheel scrolling, categories and image recovery.
- Preserve current files and private records. Browser checks use local mocked APIs, with no paid/live service calls.
- Publish verified changes to the personal main and copy the same files into the actual local runtime.

## Steps

Additional approved scope: connect real screen transitions to native browser back/forward history. Store only opaque entry IDs in history, keep drafts/results in page memory, preserve Next history fields, avoid duplicate pushes and popstate loops, restore selections/session/results, invalidate deleted sessions, and add no entry on direct load/reload. At the initial screen the browser may leave normally. Verify search → result → back → forward, saved results/session switches, reload, repeat traversal and history drawer behavior.

- [ ] Add `frontend/tests/browser/main-footer.cjs`, run against the current app and confirm missing collapsed controls fail.
- [ ] Update `frontend/components/TermGraph.jsx`: native collapsed controls/help, conditional selection controls, retained status messages.
- [ ] Update `frontend/app/page.jsx` and `frontend/app/globals.css`: notice in history, focused desktop hint, counter from 450, always available accessible 500-character limit and errors.
- [ ] Adjust the wheel browser check to open controls before using a zoom button.
- [ ] Run frontend unit tests, production build, and browser regression for repeated disclosure toggles, keyboard focus, desktop/mobile layout, selection/add/remove/search, wheel, depth/drag, buttons and pinch.
- [ ] Back up and sync only changed runtime files, rebuild/restart local frontend3100 and repeat the browser regression there.
- [ ] Publish exact files to the personal main, verify remote blobs and CI, report results and commit link.
