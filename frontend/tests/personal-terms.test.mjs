import test from "node:test";
import assert from "node:assert/strict";
import { createPersonalTermClient, editablePersonalTerm } from "../lib/personal-terms.mjs";

function response(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

test("proposal generation uses credentials, action header, and idempotency key", async () => {
  const calls = [];
  const client = createPersonalTermClient(async (url, options) => {
    calls.push([url, options]);
    return response({ term: { term_id: "personal_1", status: "proposed" }, duplicate_warnings: [] }, true, 201);
  });
  const result = await client.generate("발레 동작", "draft-1");
  assert.equal(result.term.status, "proposed");
  assert.equal(calls[0][0], "/api/personal-terms/proposals");
  assert.equal(calls[0][1].credentials, "include");
  assert.equal(calls[0][1].headers["Idempotency-Key"], "draft-1");
  assert.equal(calls[0][1].headers["x-conversation-action"], "personal-term-generate");
});
test("editing does not save until confirm is called", async () => {
  const calls = [];
  const client = createPersonalTermClient(async (url, options) => {
    calls.push([url, options]);
    return response({ term_id: "personal_1", status: url.endsWith("/confirm") ? "active" : "proposed" });
  });
  await client.update("personal_1", { label_ko: "발레 아라베스크" });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].method, "PATCH");
  await client.confirm("personal_1");
  assert.equal(calls[1][0], "/api/personal-terms/personal_1/confirm");
});

test("editor exposes user descriptions but never invents internal prompt fields", () => {
  const form = editablePersonalTerm({
    label_ko: "발레", label_en: "Ballet", role: "pose",
    plain_meaning_ko: "발레 자세입니다.", aliases_ko: ["고전 무용"],
    reference_checkpoints_ko: ["균형"], cautions_ko: [], query_fragments_en: ["ballet pose"],
  });
  assert.equal(form.plain_meaning_ko, "발레 자세입니다.");
  assert.equal("internal_question" in form, false);
});

