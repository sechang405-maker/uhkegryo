import test from 'node:test';
import assert from 'node:assert/strict';
import { createSubmissionController, submitAgentRequest } from '../lib/agent-submit.mjs';
const usage = await import('../lib/session-usage.mjs').catch(() => ({}));
import { restoreConversation, createConversation } from '../lib/server-conversation.mjs';
import * as serverConversation from '../lib/server-conversation.mjs';

const sid = '00000000-0000-0000-0000-000000000001';
const quota = count => ({ message_count: count, message_limit: 20, remaining_messages: Math.max(0, 20-count), can_submit: count < 20 });
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const storage = () => { const data = new Map(); return { getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k), data }; };

test('quota comes from server totals even when history is paginated or legacy total exceeds 20', () => {
  assert.equal(typeof usage.sessionUsage, 'function', 'server usage normalization is missing');
  assert.deepEqual(usage.sessionUsage(quota(19)), quota(19));
  assert.deepEqual(usage.sessionUsage({ ...quota(24), remaining_messages: -4, can_submit: true }), quota(24));
});

test('twentieth acceptance retains job and usage; twenty-first is a definitive quota error', async () => {
  const accepted = await submitAgentRequest('twentieth', { sessionId: sid, createId: () => 'twentieth',
    fetchImpl: async () => response({ job_id: 'last-job', poll_after_ms: 100, ...quota(20) }, 202) });
  assert.equal(accepted.jobId, 'last-job');
  assert.deepEqual(accepted.usage, quota(20));
  const denied = await submitAgentRequest('twenty-first', { sessionId: sid, createId: () => 'extra',
    fetchImpl: async () => response({ failure_code: 'session_message_limit_reached', retryable: false, ...quota(20) }, 429) });
  assert.equal(denied.failureCode, 'session_message_limit_reached');
  assert.equal(denied.retryable, false);
  assert.deepEqual(denied.usage, quota(20));
});

test('ambiguous network acceptance reuses its key after reload without persisting text or charging locally', async () => {
  const saved = storage(), keys = [];
  const options = { sessionId: sid, storage: saved, createId: () => 'original-key',
    fetchImpl: async (_url, init) => { keys.push(init.headers['Idempotency-Key']); throw Error('connection lost'); } };
  await createSubmissionController().submit('private character details', options);
  assert.equal([...saved.data.values()].some(value => value.includes('private character details')), false);
  const reloaded = createSubmissionController();
  assert.equal(await reloaded.canRetry('private character details', options), true);
  assert.equal(await reloaded.canRetry('different text', options), false);
  const retried = await reloaded.submit('private character details', { ...options, usage: quota(20), createId: () => 'must-not-use',
    fetchImpl: async (_url, init) => { keys.push(init.headers['Idempotency-Key']); return response({ job_id: 'same-job', ...quota(20) }, 202); } });
  assert.equal(retried.jobId, 'same-job');
  assert.deepEqual(keys, ['original-key', 'original-key']);
  assert.equal(await reloaded.canRetry('private character details', options), false);
});

test('new input at cap does not call network and acknowledged intentional repeat gets a fresh key', async () => {
  const saved = storage(), controller = createSubmissionController(), keys = []; let sequence = 0;
  const options = { sessionId: sid, storage: saved, createId: () => `key-${++sequence}`,
    fetchImpl: async (_url, init) => { keys.push(init.headers['Idempotency-Key']); return response({ job_id: `job-${sequence}`, ...quota(sequence) }, 202); } };
  await controller.submit('same text', options); await controller.submit('same text', options);
  assert.deepEqual(keys, ['key-1', 'key-2']);
  const denied = await controller.submit('new input', { ...options, usage: quota(20) });
  assert.equal(denied.failureCode, 'session_message_limit_reached'); assert.equal(keys.length, 2);
});

test('5xx or invalid acknowledgement keeps key; definitive rejection and validation never charge usage', async () => {
  const saved = storage(), controller = createSubmissionController();
  const options = { sessionId: sid, storage: saved, createId: () => 'pending', fetchImpl: async () => response({}, 503) };
  await controller.submit('request', options);
  assert.equal(await controller.canRetry('request', options), true);
  await controller.submit('request', { ...options, fetchImpl: async () => response({}, 202) });
  assert.equal(await controller.canRetry('request', options), true);
  await controller.submit('request', { ...options, fetchImpl: async () => response({ user_message: 'invalid' }, 422) });
  assert.equal(await controller.canRetry('request', options), false);
  const result = await controller.submit('', options); assert.equal(result.usage, undefined);
});

test('storage failure prevents a request whose retry key could be lost on reload', async () => {
  let calls = 0;
  const result = await createSubmissionController().submit('request', { sessionId: sid,
    storage: { getItem: () => null, setItem: () => { throw Error('quota'); } },
    fetchImpl: async () => { calls++; return response({ job_id: 'bad' }, 202); } });
  assert.equal(result.ok, false); assert.equal(calls, 0);
});

test('restore, focus refresh and server-created new session expose server usage without extra jobs', async () => {
  const calls = [], fetchImpl = async (url, init) => {
    calls.push([url, init.method || 'GET']);
    if (url.endsWith('/jobs?latest=true&limit=20')) return response({ items: [] });
    if (url === '/api/sessions') return response({ session_id: sid, created_at: '2026-10-20T00:00:00Z', ...quota(0) }, 201);
    return response({ session_id: sid, ...quota(24) });
  };
  const restored = await restoreConversation({ sessionId: sid, fetchImpl });
  assert.deepEqual(restored.usage, quota(24));
  assert.deepEqual(await serverConversation.readConversationUsage({ sessionId: sid, fetchImpl }), quota(24));
  const created = await createConversation({ fetchImpl }); assert.deepEqual(usage.sessionUsage(created), quota(0));
  assert.equal(calls.some(([url]) => url === '/api/agent'), false);
});

test('another tab acknowledging recovery cannot replace this tab ambiguous attempt key, including reload', async () => {
  const shared = storage(), tabA = storage(), tabB = storage(), keys = [];
  const options = { sessionId: sid, storage: shared, createId: () => 'original',
    fetchImpl: async (_url, init) => { keys.push(init.headers['Idempotency-Key']); throw Error('lost receipt'); } };
  const original = createSubmissionController();
  await original.submit('same request', { ...options, attemptStorage: tabA });
  const accept = async (_url, init) => { keys.push(init.headers['Idempotency-Key']); return response({ job_id: 'original-job', ...quota(20) }, 202); };
  await createSubmissionController().submit('same request', { ...options, attemptStorage: tabB, fetchImpl: accept });
  assert.equal(await original.canRetry('same request', { ...options, attemptStorage: tabA }), true);
  const reloadedA = createSubmissionController();
  assert.equal(await reloadedA.canRetry('same request', { ...options, attemptStorage: tabA }), true);
  const recovered = await reloadedA.submit('same request', { ...options, attemptStorage: tabA, createId: () => 'duplicate', usage: quota(20), fetchImpl: accept });
  assert.equal(recovered.jobId, 'original-job'); assert.deepEqual(keys, ['original', 'original', 'original']);
  await reloadedA.submit('same request', { ...options, attemptStorage: tabA, createId: () => 'intentional-repeat', fetchImpl: accept });
  assert.equal(keys.at(-1), 'intentional-repeat');
});

test('an old attempt acknowledgement cannot remove another tab newer ambiguous key', async () => {
  const shared = storage(), tabA = storage(), tabB = storage(), keys = [];
  const lost = async (_url, init) => { keys.push(init.headers['Idempotency-Key']); throw Error('lost receipt'); };
  const accepted = async (_url, init) => { keys.push(init.headers['Idempotency-Key']); return response({ job_id: 'accepted' }, 202); };
  const options = { sessionId: sid, storage: shared, createId: () => 'first', fetchImpl: lost };
  const a = createSubmissionController(), b = createSubmissionController();
  await a.submit('request', { ...options, attemptStorage: tabA });
  await b.submit('request', { ...options, attemptStorage: tabB, fetchImpl: accepted });
  await b.submit('request', { ...options, attemptStorage: tabB, createId: () => 'second' });
  await a.submit('request', { ...options, attemptStorage: tabA, fetchImpl: accepted });
  await createSubmissionController().submit('request', { ...options, attemptStorage: tabB, createId: () => 'duplicate', fetchImpl: accepted });
  assert.deepEqual(keys, ['first', 'first', 'second', 'first', 'second']);
});
