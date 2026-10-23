# Recommendation adoption search implementation plan

**Goal:** Offer numbered drawing ideas, adopt only the selected candidate as search evidence, and connect the resulting gallery and Pinterest query.

**Architecture:** Store bounded recommendation groups and adoption provenance in existing job/result JSON and same-session memory. Keep ordinary dialogue and recommendation-only turns out of search. Revalidate adopted cards against the current catalog and preserve the last successful gallery on failed recommendation searches.

**Global constraints:** Current explicit conditions > prior user-confirmed conditions > adopted recommendation supplements, scoped to the same topic and session. No answer buttons, freeform queries, paragraph prompt edits, global settings, production/team services, or unrelated UI changes. Personal main publication and runtime copy synchronization are authorized.

## Task 1: Backend recommendation contract and adoption

- [ ] Add bounded typed candidates (stable server-bound IDs, ordinal/name, original quote, card selections, unsupported constraints), groups, adoption request evidence and topic scope. Persist through existing result/memory JSON without a DB migration.
- [ ] Generate two or three numbered text candidates for recommendation-only requests without changing selected cards. Handle a single adopted candidate or explicit ordinal/name; ambiguous candidates yield a selection-only question. Recommend-and-search selects one candidate under explicit authorization.
- [ ] Validate only adopted candidate evidence, IDs, ownership, and current active catalog state. Preserve explicit overrides and prior confirmed constraints within topic; avoid injecting unrelated history. Surface unsupported core conditions without a search.
- [ ] Add deterministic schema/grounding/memory/worker tests covering recommendation-only, single/multiple adoption, ambiguity, one-shot, overrides, topic/session isolation, inactive cards, failures/retry/restore, and rejected fabricated evidence. Run targeted tests then full backend suite.

## Task 2: Frontend result integration

- [ ] Reuse the text answer and chat composer with no answer buttons. Preserve previous gallery on failed recommendation searches and derive top Pinterest query from the active successful search.
- [ ] Extend deterministic frontend tests and a desktop/mobile mock browser scenario: recommendation text, ambiguous choice, selection/override, successful gallery and top query, failed search retaining gallery, reload/session isolation. Preserve graph, upward autosize, chevron and 16px end padding.
- [ ] Run frontend tests, production build and existing composer/scroll/history regressions. Review combined diff for spec and quality.

## Task 3: Runtime and main

- [ ] Compare changed runtime files to HEAD, back up and sync only changed files. Build runtime frontend; restart only inspected existing Uhkegryo processes needing new source.
- [ ] Verify actual3100 using local mocks. Publish exact files to sechang405-maker/uhkegryo main, fast-forward local checkout, compare remote blobs/source/runtime and wait for Tests/Secret Scan.
- [ ] Record completed/failed/unexecuted checks, commit URL and exact remaining blockers separately from publication status.
