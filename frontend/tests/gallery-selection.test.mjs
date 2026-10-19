import test from "node:test";
import assert from "node:assert/strict";
import { createGallerySelection } from "../lib/gallery-selection.mjs";

const sid = "session-a";
const job = (id, session = sid, result = { reference_plan: { terms: [{ term_id: id }] } }) =>
  ({ job_id: id, session_id: session, job_status: "completed", result });
const entry = (id, session = sid) => ({ id, job: job(id, session) });
const response = (body, ok = true) => ({ ok, json: async () => body });
function setup() {
  const pending = [], state = { job: null, selected: null, loading: false, error: "" };
  const gallery = createGallerySelection({
    onJob: (job) => { state.job = job; },
    onSelection: (id) => { state.selected = id; },
    onState: (value) => Object.assign(state, value),
    fetchImpl: (url, options) => new Promise((resolve) => pending.push({ url, options, resolve })),
  });
  gallery.reset(sid);
  return { gallery, pending, state };
}

test("live polling continues without replacing the selected historical gallery", async () => {
  const { gallery, pending, state } = setup();
  const selected = gallery.open(entry("old"));
  gallery.live(job("latest"), sid);
  assert.equal(state.job, null);
  pending[0].resolve(response(job("old"))); await selected;
  gallery.live(job("latest"), sid);
  assert.equal(state.job.job_id, "old");
  assert.equal(state.selected, "old");
});

test("fast selections ignore late success and late errors", async () => {
  for (const ok of [true, false]) {
    const { gallery, pending, state } = setup();
    const a = gallery.open(entry("a")), b = gallery.open(entry("b"));
    pending[1].resolve(response(job("b"))); await b;
    pending[0].resolve(response(job("a"), ok)); await a;
    assert.equal(state.job.job_id, "b"); assert.equal(state.error, "");
  }
});

test("session switch, new session and back cancel pending history and clear gallery", async () => {
  for (const next of ["session-b", null, sid]) {
    const { gallery, pending, state } = setup();
    const selected = gallery.open(entry("old"));
    gallery.reset(next);
    pending[0].resolve(response(job("old"))); await selected;
    assert.equal(pending[0].options.signal.aborted, true);
    assert.equal(state.job, null); assert.equal(state.selected, null);
    if (next !== sid) { gallery.live(job("old"), sid); assert.equal(state.job, null); }
  }
});

test("history failure and empty result never retain another gallery", async () => {
  const { gallery, pending, state } = setup();
  gallery.live(job("latest"), sid);
  const bad = gallery.open(entry("bad"));
  assert.equal(state.job, null);
  pending[0].resolve(response({}, false)); await bad;
  assert.ok(state.error); assert.equal(state.job, null);
  const empty = gallery.open(entry("empty"));
  pending[1].resolve(response(job("empty", sid, { reference_plan: null }))); await empty;
  assert.equal(state.error, ""); assert.equal(state.job.result.reference_plan, null);
});

test("cross-session selection and mismatched response cannot be displayed", async () => {
  const { gallery, pending, state } = setup();
  await gallery.open(entry("other", "session-b"));
  assert.equal(pending.length, 0);
  const selected = gallery.open(entry("old"));
  pending[0].resolve(response(job("old", "session-b"))); await selected;
  assert.equal(state.job, null); assert.ok(state.error);
});

test("returning to live selection accepts only its session", () => {
  const { gallery, state } = setup();
  gallery.reset(sid); gallery.live(job("new"), sid);
  assert.equal(state.job.job_id, "new");
  gallery.live(job("foreign", "session-b"), "session-b");
  assert.equal(state.job.job_id, "new");
});

test("browser restoration cancels stale history and protects the restored selection from live updates", async () => {
  const { gallery, pending, state } = setup();
  const loading = gallery.open(entry("pending"));
  gallery.restore(job("restored"), "restored", sid);
  gallery.live(job("new"), sid);
  assert.equal(state.job.job_id, "restored");
  assert.equal(state.selected, "restored");
  pending[0].resolve(response(job("pending"))); await loading;
  assert.equal(state.job.job_id, "restored");
  assert.equal(pending[0].options.signal.aborted, true);
  gallery.restore(job("live"), null, sid);
  gallery.live(job("latest"), sid);
  assert.equal(state.job.job_id, "latest");
});
