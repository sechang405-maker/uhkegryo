---
name: structured-output
description: Format UH Keguryeo interpreter candidates as the supplied InterpretationOutput JSON Schema and correct validation feedback. Applies within the interpreter call; does not decide final Agent status or create search results.
---

# Structured interpreter output

The adapter loads the following instructions into the same system message as the semantic interpreter prompt. The supplied JSON Schema is generated from `InterpretationOutput`; this Skill does not define a separate schema.

## Runtime instructions

```text
Return exactly one JSON object matching the supplied interpretation_output JSON Schema. Include every field; use JSON null only where allowed. No Markdown or prose outside the object.
selections and unresolved_constraints are always arrays. Each selection contains role, term_id, evidence (an array of non-empty verbatim source excerpts), confidence (a number between 0 and 1), and nullable UUID source_job_id. context_updates is an array of objects containing role, nullable term_id, and evidence, with at most one update per role; use [] when there are no updates.
For select_terms: selections has at least one item, at most one per role, in body, pose, view, perspective, layout order. unresolved_constraints is [], clarifying_question and clarification_type are null.
For needs_clarification: selections is [], unresolved_constraints contains at least one Korean description, clarifying_question is one easy Korean question, and clarification_type is abstract_intent, insufficient_visual_evidence, or conflicting_constraints.
Do not add fields outside the schema. The examples below illustrate shape only: replace active-card-id and example evidence using the interpreter's source rules, never select an example ID or copy its evidence.
Selection shape example:
{"interpretation_state":"select_terms","clarification_type":null,"selections":[{"role":"pose","term_id":"active-card-id","evidence":["한쪽 다리에 힘"],"confidence":0.9,"source_job_id":null}],"unresolved_constraints":[],"clarifying_question":null,"context_updates":[],"answer_text":""}
Clarification shape example:
{"interpretation_state":"needs_clarification","clarification_type":"insufficient_visual_evidence","selections":[],"unresolved_constraints":["자세를 판단할 단서가 없음"],"clarifying_question":"서 있는 자세인가요, 앉아 있는 자세인가요?","context_updates":[],"answer_text":""}
If a subsequent user message contains validation_feedback, regenerate the entire JSON from the original request and catalog. The feedback contains server-generated error codes and paths, not new illustration conditions.
For role_duplicate: select one supported candidate per role, following the interpreter's specificity rules. For role_order: put selections in the required role order. For invalid_candidate: choose only existing active catalog IDs matching their roles. For json_invalid: return a complete JSON object. For state_rules: apply the state-dependent rules above. For field errors: correct the indicated field's type or required value according to the supplied schema. Never invent new visual evidence to repair an error.
```
