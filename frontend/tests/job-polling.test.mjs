import test from "node:test";
import assert from "node:assert/strict";
import { createJobPoller, pollDelay } from "../lib/job-polling.mjs";

test("AC-01/02: 서버 간격으로 진행 상태를 조회하고 완료에서 멈춘다", async () => {
  const timers = [];
  const updates = [];
  const calls = [];
  const jobs = [
    { job_status: "queued", poll_after_ms: 1200 },
    { job_status: "searching", poll_after_ms: 700 },
    { job_status: "completed", poll_after_ms: null, result: {} },
  ];
  const poller = createJobPoller("job-1", {
    fetchImpl: async (...args) => {
      calls.push(args);
      return { ok: true, json: async () => jobs.shift() };
    },
    schedule: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    cancel: () => {},
    onUpdate: (job) => updates.push(job.job_status),
    onError: () => assert.fail("unexpected polling error"),
  });
  poller.start(500);
  for (const delay of [500, 1200, 700]) {
    const timer = timers.shift();
    assert.equal(timer.ms, delay);
    await timer.fn();
  }
  assert.deepEqual(updates, ["queued", "searching", "completed"]);
  assert.equal(timers.length, 0);
  assert.equal(calls.length, 3);
  assert.equal(calls[0][0], "/api/jobs/job-1");
  assert.equal(calls[0][1].credentials, "include");
  poller.stop();
});

test("AC-02/03: 정리된 조회는 화면을 갱신하지 않고 오류는 재예약하지 않는다", async () => {
  let release;
  let tick;
  let updated = false;
  let error = "";
  const poller = createJobPoller("job-2", {
    fetchImpl: () => new Promise((resolve) => { release = resolve; }),
    schedule: (fn) => { tick = fn; return 1; },
    cancel: () => {},
    onUpdate: () => { updated = true; },
    onError: (message) => { error = message; },
  });
  poller.start();
  const pending = tick();
  poller.stop();
  release({ ok: true, json: async () => ({ job_status: "completed" }) });
  await pending;
  assert.equal(updated, false);
  assert.equal(error, "");

  let scheduled = 0;
  const failed = createJobPoller("job-3", {
    fetchImpl: async () => ({ ok: false }),
    schedule: (fn) => { scheduled += 1; tick = fn; return scheduled; },
    cancel: () => {},
    onUpdate: () => assert.fail("unexpected update"),
    onError: (message) => { error = message; },
  });
  failed.start();
  await tick();
  assert.match(error, /상태를 불러오지 못했습니다/);
  assert.equal(scheduled, 1);
  failed.stop();
  assert.equal(pollDelay(null), 1000);
});
