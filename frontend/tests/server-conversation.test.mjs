import test from "node:test";
import assert from "node:assert/strict";
import { restoreConversation, createConversation, listConversations, resumeConversation, createHistoryLoader } from "../lib/server-conversation.mjs";
import { showThumbnail } from "../lib/result-view.mjs";
import { submitAgentRequest } from "../lib/agent-submit.mjs";
import { answerForJob, upsertTurn, stopTurnPolling } from "../lib/conversation.mjs";
const sid = "00000000-0000-0000-0000-000000000001";
const sid2 = "00000000-0000-0000-0000-000000000002";
const job = (id, status = "completed") => ({ job_id: id, session_id: sid, job_status: status,
  request_text: `요청 ${id}`, result: status === "completed" ? { agent_status: "partial_result", answer_text: "통합 설명", reason_codes: ["PIN_SEARCH_UNAVAILABLE"] } : null });
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

test("완료 2건 복원 후 이전 기록만 재조회해 정상 썸네일을 표시하고 더미는 즉시 연다", async () => {
  const pin = { status: "available", pin_url: "https://www.pinterest.com/pin/123/" };
  const stored = [job("old"), job("latest")].map((j) => ({ ...j, result: { reference_plan: { terms: [{ pins: [pin] }] } } }));
  const enriched = (j) => ({ ...j, result: { reference_plan: { terms: [{ pins: [{ ...pin, thumbnail_url: "https://i.pinimg.com/fixture.jpg" }] }] } } });
  const calls = [], fetchImpl = async (url, options) => {
    calls.push(url); assert.equal(options.credentials, "include"); assert.equal(options.cache, "no-store");
    return response(url.includes("offset=") ? { items: stored } : url.includes("/api/jobs/")
      ? enriched(stored.find((j) => url.endsWith(j.job_id))) : { items: [{ session_id: sid }], session_id: sid });
  };
  const { turns } = await restoreConversation({ fetchImpl });
  assert.equal(showThumbnail(turns[0].job.result.reference_plan.terms[0].pins[0]), false);
  let selected; const states = [];
  const loader = createHistoryLoader({ fetchImpl, onJob: (j) => { selected = j; }, onState: (s) => states.push(s) });
  await loader.open(turns[0]); assert.equal(calls.at(-1), "/api/jobs/old");
  assert.equal(showThumbnail(selected.result.reference_plan.terms[0].pins[0]), true);
  assert.equal(states.some((s) => s.loading), true); assert.equal(states.at(-1).loading, false);
  const count = calls.length; await loader.open({ ...turns[0], demo: true }); assert.equal(calls.length, count);
});

test("기록 조회 오류는 Pin 상태를 바꾸지 않고 다른 선택·정리 후 늦은 응답을 차단", async () => {
  const releases = [], states = [], selected = [], signals = [];
  const loader = createHistoryLoader({ onState: (s) => states.push(s), onJob: (j) => selected.push(j.job_id),
    fetchImpl: (_, options) => { signals.push(options.signal); return new Promise((resolve) => releases.push(resolve)); } });
  const entry = (id) => ({ id, job: job(id) });
  const failed = loader.open(entry("bad")); releases[0](response({}, 503)); await failed;
  assert.match(states.at(-1).error, /검색 기록/); assert.equal(states.at(-1).loading, false); assert.deepEqual(selected, []);
  const old = loader.open(entry("old")), next = loader.open(entry("next"));
  releases[2](response(job("next"))); await next; releases[1](response(job("old"))); await old;
  assert.equal(signals[1].aborted, true); assert.deepEqual(selected, ["next"]);
  const removed = loader.open(entry("removed")); loader.cancel(); releases[3](response(job("removed"))); await removed;
  assert.equal(signals[3].aborted, true); assert.deepEqual(selected, ["next"]);
});

test("서버 페이지 전체 복원, 중복 제거, 마지막 결과 enrichment, 쿠키와 취소 signal", async () => {
  const calls = [], controller = new AbortController();
  const restored = await restoreConversation({ signal: controller.signal, fetchImpl: async (url, options) => {
    calls.push(url);
    assert.equal(options.credentials, "include"); assert.equal(options.cache, "no-store");
    assert.equal(options.signal, controller.signal);
    if (url === "/api/sessions?limit=1") return response({ items: [{ session_id: sid }] });
    if (url.endsWith("offset=0")) return response({ items: Array.from({ length: 100 }, (_, i) => job(`${i}`)) });
    if (url.endsWith("offset=100")) return response({ items: [job("99"), job("100")] });
    if (url.endsWith("/jobs/100")) return response({ ...job("100"), enriched: true });
    return response({ session_id: sid });
  } });
  assert.equal(restored.sessionId, sid); assert.equal(restored.turns.length, 101);
  assert.deepEqual(restored.turns.map((turn) => turn.id), Array.from({ length: 101 }, (_, i) => `${i}`));
  assert.equal(restored.turns.at(-1).job.enriched, true);
  assert.equal(answerForJob(restored.turns[0].job), "통합 설명");
  assert.equal(calls.length, 5);
});

test("미인증·빈 목록은 빈 대화이며 새 ID를 후속 제출에 명시", async () => {
  for (const r of [response({}, 401), response({ items: [] })]) {
    assert.deepEqual(await restoreConversation({ fetchImpl: async () => r }), { sessionId: null, turns: [] });
  }
  const created = await createConversation({ fetchImpl: async (url, options) => {
    assert.equal(url, "/api/sessions"); assert.equal(options.method, "POST");
    return response({ session_id: sid, created_at: "2026-10-07T01:00:00Z" }, 201);
  } });
  const sent = await submitAgentRequest("포즈만 수정", { sessionId: created.session_id, createId: () => "key", fetchImpl: async (_, options) => {
    assert.deepEqual(JSON.parse(options.body), { request_text: "포즈만 수정", session_id: sid });
    return response({ job_id: "next", poll_after_ms: 1000 }, 202);
  } });
  assert.equal(sent.ok, true);
});

test("세션 목록 복원과 선택한 세션의 대화만 복원", async () => {
  const calls = [];
  const sessions = [
    { session_id: sid2, created_at: "2026-10-07T01:00:00Z" },
    { session_id: sid, created_at: "2026-10-06T01:00:00Z" },
  ];
  const items = [job("selected", "completed")].map((entry) => ({ ...entry, session_id: sid }));
  const fetchImpl = async (url) => {
    calls.push(url);
    if (url === "/api/sessions?limit=100&offset=0") return response({ items: sessions });
    if (url === `/api/sessions/${sid}`) return response(sessions[1]);
    if (url === `/api/sessions/${sid}/jobs?limit=100&offset=0`) return response({ items });
    if (url === "/api/jobs/selected") return response(items[0]);
    throw new Error(`unexpected request ${url}`);
  };
  const listed = await listConversations({ fetchImpl });
  assert.deepEqual(listed.map((entry) => entry.session_id), [sid2, sid]);
  const restored = await restoreConversation({ fetchImpl, sessionId: sid });
  assert.equal(restored.sessionId, sid);
  assert.deepEqual(restored.turns.map((turn) => turn.id), ["selected"]);
  assert.equal(calls.some((url) => url.includes(sid2)), false);
});

test("세션 소유 쿠키가 없으면 세션 목록은 빈 목록으로 시작", async () => {
  const listed = await listConversations({ fetchImpl: async (url) => {
    assert.equal(url, "/api/sessions?limit=100&offset=0");
    return response({}, 401);
  } });
  assert.deepEqual(listed, []);
});

test("새 세션 생성 뒤 목록에서 해당 세션을 추가할 수 있는 메타데이터 반환", async () => {
  const created = { session_id: sid2, created_at: "2026-10-07T01:00:00Z" };
  const result = await createConversation({ fetchImpl: async (url, options) => {
    assert.equal(url, "/api/sessions");
    assert.equal(options.method, "POST");
    return response(created, 201);
  } });
  assert.deepEqual(result, created);
});

test("목록 장애·이력 권한 오류·손상 데이터는 복원 실패하고 fallback하지 않는다", async () => {
  for (const bad of [response({}, 503), response({}), response({ items: [{ session_id: "bad" }] })]) {
    await assert.rejects(restoreConversation({ fetchImpl: async () => bad }));
  }
  for (const bad of [response({}, 401), response({}, 404), response({ items: [job("x", "invalid")] })]) {
    await assert.rejects(restoreConversation({ fetchImpl: async (url) => url.includes("limit=1")
      && !url.includes("offset=") ? response({ items: [{ session_id: sid }] }) : url.includes("offset=") ? bad : response({}) }));
  }
  await assert.rejects(restoreConversation({ fetchImpl: async () => { throw new Error("offline"); } }));
});

test("복원된 여러 진행 turn이 각각 종결·중단되고 cleanup은 늦은 응답을 차단", async () => {
  let turns = ["a", "b", "c"].map((id) => ({ id, request: id, job: job(id, "running") }));
  const tasks = [], errors = [], updates = [];
  let release;
  const pollers = resumeConversation(turns, { schedule: (fn) => { tasks.push(fn); return tasks.length; }, cancel: () => {},
    fetchImpl: async (url) => url.endsWith("b") ? response({}, 503) : url.endsWith("c")
      ? new Promise((resolve) => { release = resolve; }) : response(job("a")),
    onUpdate: (turn) => { updates.push(turn.id); turns = upsertTurn(turns, turn); },
    onError: (id) => { errors.push(id); turns = stopTurnPolling(turns, id); },
  });
  await tasks[0](); await tasks[1](); const pending = tasks[2]();
  pollers.stop(); release(response(job("c"))); await pending;
  assert.deepEqual(updates, ["a"]); assert.deepEqual(errors, ["b"]);
  assert.equal(turns.length, 3); assert.equal(turns[1].polling_stopped, true);
  assert.equal(answerForJob(turns[0].job), "통합 설명");
});
