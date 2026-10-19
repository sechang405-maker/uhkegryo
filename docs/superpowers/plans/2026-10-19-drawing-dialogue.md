# Everyday drawing dialogue implementation plan

Approved: remember preceding drawing conversation, answer everyday drawing questions, search only when explicitly requested or continuing an established reference clarification/change, generate only contextually missing clarification questions with the existing LLM, and remove every answer-attached action button. Loss of per-answer reference reopening is accepted.

## Contract and boundaries

- Add `drawing_chat` to interpretation and final result states. It requires nonempty `answer_text`, empty selections/updates/unresolved constraints/reason codes, no reference plan and no clarification question.
- Reuse the configured interpreter/transport/auth. Apply a server-owned drawing-dialogue instruction supplement to the current prompt; no new service, credential, model or auth configuration.
- Chat uses bounded same-session user/assistant context without converting model suggestions into user constraints. Keep prior reference selections and gallery. Preserve existing reference validation, safety fallback and repetition guards.
- Browser history/restoration must retain chat/reference separation; remove only answer-attached buttons, preserving composer, graph, gallery and history controls.
- Do not modify other projects/containers or real private records during verification.

## Execution

1. Add failing schema, resolver, worker and context tests; use local fake transports/providers to prove chat and short followups do not search and explicit reference requests do.
2. Implement backend branch and bounded assistant context plus LLM routing instructions; preserve pending clarification handling and safety fallback.
3. Implement frontend answer-button removal and reference-board preservation with unit/browser regressions. Backend and frontend have separate ownership during parallel work.
4. Run targeted/full test suites, production build and independent read-only review. Resolve important findings before publishing.
5. Back up and compare affected runtime files; sync/restart only this app. Verify desktop/mobile, saved restore/back-forward, chat→followup→explicit search, context questions and no answer buttons using isolated test fixtures.
6. Publish verified files directly to personal main and verify remote blobs, runtime equality and final CI. Report publication and validation separately.

Screenshot access: official Library download failed during Windows xattr application; the requested PNG does not remain locally. Library image read returned metadata/extracted text rather than pixel content. This limitation does not block the code-confirmed approved scope.
