import test from "node:test";
import assert from "node:assert/strict";
import nextConfig from "../next.config.mjs";
import {
  countCharacters,
  createSubmissionController,
  submitAgentRequest,
  validateRequestText,
} from "../lib/agent-submit.mjs";

test("AC-01: 빈 입력과 500자 초과는 API 호출 전에 거부한다", async () => {
  let calls = 0;
  const fetchImpl = () => { calls += 1; throw new Error("must not call"); };
  for (const text of ["", "   ", "가".repeat(501)]) {
    assert.ok(validateRequestText(text));
    assert.equal((await submitAgentRequest(text, { fetchImpl })).ok, false);
  }
  assert.equal(calls, 0);
  assert.equal(countCharacters("😀".repeat(500)), 500);
  assert.equal(validateRequestText("😀".repeat(500)), null);
});

test("AC-02: 유효한 원문을 같은 origin에 UUID 키와 쿠키로 제출한다", async () => {
  const requestText = "한쪽 다리에 힘을 준 캐릭터";
  const key = "550e8400-e29b-41d4-a716-446655440000";
  let call;
  const result = await submitAgentRequest(requestText, {
    createId: () => key,
    fetchImpl: async (...args) => {
      call = args;
      return { status: 202, json: async () => ({ job_id: "job-123", poll_after_ms: 1000 }) };
    },
  });
  assert.deepEqual(result, { ok: true, jobId: "job-123", pollAfterMs: 1000 });
  assert.equal(call[0], "/api/agent");
  assert.equal(call[1].method, "POST");
  assert.equal(call[1].credentials, "include");
  assert.equal(call[1].headers["Idempotency-Key"], key);
  assert.deepEqual(JSON.parse(call[1].body), { request_text: requestText });
  const rewrites = await nextConfig.rewrites();
  assert.equal(rewrites[0].source, "/api/:path*");
  assert.match(rewrites[0].destination, /^https?:\/\/[^/]+\/api\/:path\*$/);
});

test("AC-03: 요청 중 중복 제출을 막고 서버의 사용자 메시지만 반환한다", async () => {
  let release;
  let calls = 0;
  const controller = createSubmissionController();
  const options = {
    createId: () => "550e8400-e29b-41d4-a716-446655440001",
    fetchImpl: () => {
      calls += 1;
      return new Promise((resolve) => { release = resolve; });
    },
  };
  const first = controller.submit("앉은 캐릭터", options);
  assert.equal(controller.isPending(), true);
  assert.equal(await controller.submit("앉은 캐릭터", options), null);
  assert.equal(calls, 1);
  release({ status: 422, json: async () => ({ user_message: "입력을 확인해 주세요." }) });
  assert.deepEqual(await first, { ok: false, error: "입력을 확인해 주세요." });
  assert.equal(controller.isPending(), false);
});

test("같은 원문 재검색은 새 키를 사용하고 원문을 보존한다", async () => {
  const calls = [];
  let sequence = 0;
  const controller = createSubmissionController();
  const options = {
    createId: () => `retry-${++sequence}`,
    fetchImpl: async (_url, init) => {
      calls.push(init);
      return { status: 202, json: async () => ({ job_id: `job-${sequence}`, poll_after_ms: 1000 }) };
    },
  };
  for (let attempt = 0; attempt < 2; attempt++) await controller.submit("  앉은 캐릭터  ", options);
  assert.notEqual(calls[0].headers["Idempotency-Key"], calls[1].headers["Idempotency-Key"]);
  assert.deepEqual(calls.map((init) => JSON.parse(init.body).request_text), ["  앉은 캐릭터  ", "  앉은 캐릭터  "]);
});
