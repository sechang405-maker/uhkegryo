import test from "node:test";
import assert from "node:assert/strict";
import * as chat from "../lib/conversation.mjs";
import { createJobPoller } from "../lib/job-polling.mjs";

const job = (text, status = "success") => ({ job_status: "completed", result: { agent_status: status, answer_text: text } });

test("first turn stays stopped after a 503 poll and a second completed request", async () => {
  let turns = chat.upsertTurn([], { id: "a", request: "체형", job: { job_status: "queued" }, demo: false });
  let tick;
  let calls = 0;
  const poller = createJobPoller("a", {
    fetchImpl: async (url) => {
      assert.equal(url, "/api/jobs/a");
      calls++;
      return new Response(null, { status: 503 });
    },
    schedule: (callback) => { tick = callback; return 1; }, cancel: () => {},
    onUpdate: (updatedJob) => { turns = chat.upsertTurn(turns, { id: "a", job: updatedJob }); },
    onError: () => { turns = chat.stopTurnPolling(turns, "a"); },
  });
  poller.start(1);
  await tick();
  poller.stop();
  turns = chat.upsertTurn(turns, { id: "b", request: "포즈", job: job("둘째 답변"), demo: false });
  assert.equal(calls, 1);
  assert.equal(turns[0].polling_stopped, true);
  assert.equal(chat.isTurnPending(turns[0]), false);
  assert.equal(turns[0].job.job_status, "queued");
  assert.equal(chat.answerForJob(turns[1].job), "둘째 답변");
});

test("stopped state survives nonterminal updates but clears on a real terminal response", () => {
  let turns = chat.upsertTurn([], { id: "a", request: "체형", job: { job_status: "running" } });
  turns = chat.stopTurnPolling(turns, "a");
  turns = chat.upsertTurn(turns, { id: "a", job: { job_status: "searching" } });
  assert.equal(chat.isTurnPending(turns[0]), false);
  assert.equal(turns[0].polling_stopped, true);
  turns = chat.upsertTurn(turns, { id: "a", job: job("조회로 확인한 답변") });
  assert.equal(turns[0].polling_stopped, false);
  assert.equal(chat.answerForJob(turns[0].job), "조회로 확인한 답변");
});

test("stopping polling targets only that unfinished turn, never a completed answer", () => {
  const turns = [ { id: "a", job: { job_status: "queued" } }, { id: "b", job: job("완료 답변") } ];
  const stopped = chat.stopTurnPolling(turns, "a");
  assert.equal(stopped[0].polling_stopped, true);
  assert.equal(stopped[1], turns[1]);
  assert.deepEqual(chat.stopTurnPolling(turns, "missing"), turns);
  assert.deepEqual(chat.stopTurnPolling(turns, "b"), turns);
  assert.equal(turns[0].polling_stopped, undefined);
});

test("polling updates one turn without dropping previous answers", () => {
  let turns = chat.upsertTurn([], { id: "a", request: "체형", job: job("첫 답변"), demo: false });
  turns = chat.upsertTurn(turns, { id: "b", request: "포즈", job: { job_status: "searching" }, demo: false });
  turns = chat.upsertTurn(turns, { id: "b", request: "포즈", job: job("둘째 답변"), demo: false });
  assert.deepEqual(turns.map((turn) => chat.answerForJob(turn.job)), ["첫 답변", "둘째 답변"]);
});

test("answers are independent of category and image failure", () => {
  const result = job("통합 설명", "partial_result");
  result.result.reference_plan = { terms: [{ plain_meaning_ko: "개별 설명", reason_codes: ["PIN_SEARCH_UNAVAILABLE"] }] };
  assert.equal(chat.answerForJob(result), "통합 설명");
  delete result.result.answer_text;
  assert.match(chat.answerForJob(result), /통합 답변.*연결/);
  assert.equal(chat.answerForJob({ job_status: "searching" }), "");
});

test("failure and clarification are not replaced by invented explanations", () => {
  assert.equal(chat.answerForJob({ job_status: "failed", failure: { user_message: "실패" } }), "실패");
  for (const status of ["unsafe_input", "out_of_scope"]) {
    const result = job("잘못된 답", status);
    result.result.user_message = "거절";
    assert.equal(chat.answerForJob(result), "거절");
  }
  const result = job("잘못된 답", "needs_clarification");
  result.result.clarifying_question = "어느 자세인가요?";
  assert.equal(chat.answerForJob(result), "어느 자세인가요?");
});

test("demo persistence restores text only and never writes real turns or pins", () => {
  let stored;
  const storage = { setItem: (_, value) => { stored = value; }, getItem: () => stored };
  const demo = job("미리보기");
  demo.result.reference_plan = { terms: [{ pins: [{ thumbnail_url: "https://image" }] }] };
  assert.equal(chat.saveDemoTurns(storage, [{ id: "a", request: "설명", job: demo, demo: true },
    { id: "secret", request: "실제 요청", job: job("실제 답"), demo: false }]), true);
  assert.equal(stored.includes("https://image"), false);
  assert.equal(stored.includes("실제 요청"), false);
  const restored = chat.readDemoTurns(storage);
  assert.equal(restored.length, 1);
  assert.equal(chat.answerForJob(restored[0].job), "미리보기");
});

test("corrupt or inaccessible storage does not crash and saving reports failure", () => {
  for (const value of ["{", "{}", '[{"id":"x"}]']) {
    assert.equal(chat.readDemoTurns({ getItem: () => value }), null);
  }
  const storage = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(chat.readDemoTurns(storage), null);
  assert.equal(chat.saveDemoTurns(storage, []), false);
});

test("dummy followup references previous request without pretending to interpret", () => {
  const result = chat.demoReplyJob("포즈만 바꿔줘", [{ request: "허리가 좁은 캐릭터" }], job("첫 답"));
  assert.match(chat.answerForJob(result), /허리가 좁은 캐릭터/);
  assert.match(chat.answerForJob(result), /포즈만 바꿔줘/);
  assert.match(chat.answerForJob(result), /더미/);
});
