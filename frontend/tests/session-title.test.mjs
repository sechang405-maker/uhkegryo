import test from 'node:test';
import assert from 'node:assert/strict';
import { sessionTitle } from '../lib/session-title.mjs';
import { mergeSessions } from '../lib/server-conversation.mjs';
import { HOME_TERMS } from '../lib/home-catalog.mjs';
import { createDemoSessionStore } from '../lib/portfolio-demo-sessions.mjs';

test('history uses multiple card names and preserves full long names', () => {
  const long = '긴 이름'.repeat(80);
  assert.equal(sessionTitle({title_terms: [{label_ko: long}, {label_ko: '옆모습'}]}), `${long} · 옆모습`);
});
test('legacy IDs recover catalog names; missing records have safe titles', () => {
  assert.equal(sessionTitle({title_terms: [HOME_TERMS[0].term_id]}), HOME_TERMS[0].label_ko);
  assert.equal(sessionTitle({title_terms: [{term_id:'retired'}]}), '이름 없는 텀카드');
  assert.equal(sessionTitle({created_at:'2026-01-01'}), '검색 기록');
});
test('list refresh updates titles while session restoration preserves them', () => {
  const items = mergeSessions([{session_id:'a',title_terms:[{label_ko:'이전'}]}], [{session_id:'a',title_terms:[{label_ko:'새 카드'}]}]);
  assert.equal(sessionTitle(mergeSessions(items,[{session_id:'a',created_at:'2026-01-01'}])[0]), '새 카드');
});
test('demo saved sessions expose fixture card names', () => {
  const store = createDemoSessionStore({getItem:()=>null,setItem:()=>{}});
  assert.notEqual(sessionTitle(store.list()[0]), '검색 기록');
});
