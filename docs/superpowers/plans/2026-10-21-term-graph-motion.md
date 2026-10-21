# Term Graph Motion Implementation Plan

1. Add pure graph-presence helpers and red tests for reconciliation, reversal,
   cleanup, reduced motion, and shared projected points.
2. Integrate the helper into `TermGraph` with immediate logical state, a retained
   exit display graph, one pausable RAF clock, and media-query cleanup.
3. Add restrained glow and interaction feedback with a reduced-motion override.
4. Run focused and full frontend tests, production build, and fixed-build browser
   interaction checks. Confirm the existing world-layout tests remain unchanged.
5. Sync the approved personal repository and runtime copy, push `main`, and verify
   CI for the exact commit.

