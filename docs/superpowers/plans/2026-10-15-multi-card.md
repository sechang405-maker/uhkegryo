# Category-independent multiple cards

Status: approved design, 2026-10-15. Supersedes the earlier compound-pose plan; no further design approval is required.

## Contract

Every category (body, pose, view, perspective, layout) can contain multiple compatible, independently evidenced ordinary cards. Categories group and order the display; they are not selection slots. Selection arrays and final plans contain at most 10 globally unique term IDs, sorted by category with same-category cards adjacent. Duplicate IDs are invalid; duplicate categories are valid. Preserve per-card evidence, source validation, confidence gates, direct-search restrictions, and clarification/security boundaries.

`selections` and `context_updates` are arrays in the structured model schema, not nullable fields for each role. A context update is `{role, term_id, evidence, remove_term_ids}`. Adding a term adds or refreshes that card alone. Explicit replacement/removal names only the affected same-role IDs in `remove_term_ids`. Null term plus nonempty removal list removes those cards only; legacy null term with no removals clears the role. Current-request verbatim evidence is required for all mutations. Ambiguous replacement preserves constraints and asks for clarification.

For curated expressions 앉아쏴/앉아 쏴, select ordinary `pose_sitting` and `pose_action_two_hand_aiming` independently. For 서서쏴/서서 쏴, select `pose_standing` and `pose_action_two_hand_aiming`. Generic shooting does not imply two-hand geometry. A follow-up changing only sitting to standing removes `pose_sitting`, adds `pose_standing`, and preserves aiming. Non-pose categories follow the same multiplicity rule; contradictory facts still require clarification.

Saved legacy composite cards remain readable and revalidatable but are excluded from new model candidate lists. New selection never creates a compound ID. Existing single-card saved results remain valid; no storage migration is required. Search, retries, image/sketch actions, context reuse, and rendering identify individual cards by term ID, including multiple cards of the same category.

## Implementation and verification plan

1. Replace role uniqueness with global term-ID uniqueness and the 10-card limit in interpretation, result, and conversation contracts. Keep stable category ordering.
2. Expose ordinary selectable catalog cards; keep legacy composites only for compatibility. Preserve curated alias evidence without inferring geometry from generic shooting.
3. Merge conversation constraints by term ID; apply explicit removals and additions while preserving unrelated cards in the same role. Validate the final plan limit before publishing it.
4. Carry individual term IDs through search, retry, persistence, recall, sketch/image actions, and UI keys/grouping. Do not collapse cards into role-indexed maps.
5. Align every configurable local prompt, runtime output skill, and API contract with the array schema and replacement semantics.
6. Run local regressions for two same-role cards, multiple non-pose cards, unique IDs/order/10-card boundaries, sitting-to-standing replacement retaining aiming, targeted removal and legacy clear-role, saved composite read compatibility and candidate exclusion, per-card search/action isolation, invalid evidence, negation, conflicts, and genuine catalog limitations. Do not use real models, Docker, secrets, or remote services. Mocked tests establish deterministic behavior only, not real-model interpretation quality.
