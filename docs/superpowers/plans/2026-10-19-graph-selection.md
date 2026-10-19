# Graph selection query and Pinterest search alignment plan

User-approved scope: synchronize the top Pinterest query with selected card combinations, horizontally center the Pinterest search area in the window, preserve drafts, and run external searches only on explicit action. Graph coordinates, camera, and rotation must remain unchanged.

1. Add query-combination unit regressions plus a browser regression that fails on the old node selection behavior and search alignment.
2. Retain complete catalog query phrases and deduplicate the drawing/reference suffix; use the existing default recommendation when no cards are selected. Do not write to the text draft.
3. Make node activation toggle selection; preserve keyboard focus as preview only. Keep existing graph projection and gesture code unchanged.
4. Center the search area in the window at desktop/mobile widths while reserving space for the history logo; keep tooltips, explicit link and mobile panel behavior. Restore selected IDs through existing browser history snapshots.
5. Verify multiple selection, deselection, rapid activation, keyboard/list, back/forward, mobile/reduced-motion, no automatic API/external requests, and the existing footer/wheel/3D regressions.
6. Back up and sync only changed runtime files, build/restart3100, repeat local mock checks, publish to personal main, verify remote files and CI.
