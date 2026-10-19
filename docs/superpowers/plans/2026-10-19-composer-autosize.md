# Single-line autosizing composer implementation plan

Approved: one-line44px textarea, wrap/newline growth and deletion shrink, maximum min(164px,25% visible viewport) with at least44px, internal overflow, send button inside shared frame at bottom right, no text/button overlap. Keep existing Enter/Shift+Enter/IME rules,500-character validation, pane width, desktop internal padding and16px answer-end clearance. No LLM changes.

Layout constraint disclosed before implementation: current composer is anchored at viewport bottom with only26px below it. Keeping this placement means the whole input grows upward, while new text lines run downward. Downward-only outer growth would require reserving otherwise blank maximum-height space or scrolling the whole workspace; neither is introduced.

- [ ] Add RED browser regression at existing3100 (initial138px vs44px expected) and unit contracts for viewport cap, shrink and conversation end anchoring.
- [ ] Add frontend/lib/composer-autosize.mjs with resizeComposerInput(input,{viewportHeight,scrollContainer}); ignore hidden inputs, preserve older-message reading position, keep end readers at end.
- [ ] Page layout effect resizes on value/tab restoration; observe textarea width and window/visualViewport resize with cleanup. No request/keyboard controller changes.
- [ ] Move existing submit button inside frame; CSS grid minmax(0,1fr)/auto, gap8px, bottom alignment and44px button hit target. One-row textarea,10px padding,44px initial height. Existing help/count/error stay outside frame.
- [ ] Reserve the existing desktop hint row and toggle only its visibility, keeping the send button still when focus enters/leaves the whole composer. Cover both input-to-button and answer-to-button pointer paths.
- [ ] Verify bounded paste, deletion, reset, restore/back/forward, resize/small viewport, loading, composition safety, keyboard button activation and last-answer clearance; adapt width browser assertions to shared frame rather than old138px fixed textarea.
- [ ] Run units/build, independent read-only review, baseline-safe runtime backup/sync, actual3100 browser, personal main publication, source/runtime/remote blob match and final CI.
