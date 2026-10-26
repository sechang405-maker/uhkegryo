import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { reopenableReferenceTurnIds } from "../lib/result-view.mjs";

const availablePin = (id) => ({ pin_id: id, pin_url: `https://example.test/${id}`, status: "available" });
const term = (id, pins = [availablePin(`${id}-pin`)]) => ({
  role: "pose", term_id: id, label_ko: id, pins,
});
const completed = (id, result) => ({
  id,
  request: id,
  job: { job_id: id, session_id: "session-a", job_status: "completed", result },
});

test("only answers with stored usable references expose a reopen action", () => {
  const turns = [
    completed("reference", { agent_status: "success", reference_plan: { terms: [term("sitting")] } }),
    completed("chat", { agent_status: "drawing_chat", answer_text: "설명만 제공" }),
    completed("empty", { agent_status: "success", reference_plan: { terms: [] } }),
    completed("deleted", { agent_status: "success", reference_plan: {
      terms: [term("deleted", [{ pin_id: "gone", status: "deleted" }])],
    } }),
    { id: "failed", request: "failed", job: { job_id: "failed", job_status: "failed" } },
  ];

  assert.deepEqual([...reopenableReferenceTurnIds(turns)], ["reference"]);
});

test("incremental answers reuse their own composed stored board", () => {
  const body = { ...term("body"), role: "body" };
  const pose = term("pose");
  const turns = [
    completed("first", { agent_status: "success", reference_plan: { terms: [body] } }),
    completed("second", {
      agent_status: "success",
      reference_plan: { terms: [pose] },
      reference_update: {
        preserved_term_ids: ["body"], replaced_term_ids: ["pose"], removed_term_ids: [],
      },
    }),
  ];

  assert.deepEqual([...reopenableReferenceTurnIds(turns)], ["first", "second"]);
});

test("conversation answers wire an explicit saved-reference action without submission", () => {
  const panel = readFileSync(new URL("../components/ConversationPanel.jsx", import.meta.url), "utf8");
  const page = readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");

  assert.match(panel, /reopenableTurnIds\.has\(turn\.id\)/);
  assert.match(panel, /onOpenReferences\(turn\)/);
  assert.match(panel, /이 답변의 레퍼런스 보기/);
  assert.match(page, /reopenableReferenceTurnIds\(turns\)/);
  assert.match(page, /onOpenReferences=\{openTurn\}/);
  const openTurn = page.slice(page.indexOf("  function openTurn(turn)"), page.indexOf("  function fillInput", page.indexOf("  function openTurn(turn)")));
  assert.match(openTurn, /setMobilePanel\("reference"\)/);
  assert.match(openTurn, /gallerySelectionRef\.current\.open\(turn\)/);
  assert.doesNotMatch(openTurn, /submit\(|\/api\/agent/);
  assert.match(page, /createMindMapSlots\(filterLiveTerms\([\s\S]*renderedResultTerms\(job, turns, referenceJob\)/);
});
