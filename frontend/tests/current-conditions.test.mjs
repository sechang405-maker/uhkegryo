import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  createConditionRemovalController,
  readCurrentConditions,
  removeCurrentCondition,
} from '../lib/current-conditions.mjs';

const SESSION = '11111111-1111-4111-8111-111111111111';
const pageSource = readFileSync(new URL('../app/page.jsx', import.meta.url), 'utf8');
const cssSource = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

test('condition client reads and removes through the owner-scoped deterministic API', async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push([url, options]);
    return { ok: true, json: async () => ({ items: [{ term_id: 'pose_sitting', label_ko: '앉기', role: 'pose' }] }) };
  };
  assert.equal((await readCurrentConditions(SESSION, { fetchImpl })).length, 1);
  assert.equal((await removeCurrentCondition(SESSION, 'pose_sitting', { fetchImpl })).length, 1);
  assert.equal(calls[1][1].method, 'DELETE');
  assert.equal(calls[1][1].headers['X-Conversation-Action'], 'remove-condition');
});

test('latest removal result wins after rapid clicks and session changes invalidate stale replies', async () => {
  const applied = [];
  const controller = createConditionRemovalController((items) => applied.push(items));
  const first = controller.begin(SESSION);
  const second = controller.begin(SESSION);
  controller.resolve(first, [{ term_id: 'old' }]);
  controller.resolve(second, [{ term_id: 'new' }]);
  assert.deepEqual(applied, [[{ term_id: 'new' }]]);

  const stale = controller.begin(SESSION);
  controller.reset('22222222-2222-4222-8222-222222222222');
  controller.resolve(stale, [{ term_id: 'stale' }]);
  assert.deepEqual(applied, [[{ term_id: 'new' }]]);
});

test('current conditions stay outside chat scrolling and expose accessible remove controls', () => {
  assert.ok(pageSource.indexOf('className="current-conditions"') < pageSource.indexOf('className="panel-top"'));
  assert.match(pageSource, /aria-label=\{`\$\{condition\.label_ko\} 검색 조건 해제`\}/);
  assert.match(pageSource, /해제하면 다음 검색부터 제외됩니다/);
  assert.match(cssSource, /\.current-condition-chip button:disabled/);
});
