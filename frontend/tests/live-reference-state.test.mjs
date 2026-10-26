import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterLiveTerms,
  readLiveReferenceState,
  writeLiveReferenceState,
} from '../lib/live-reference-state.mjs';

const SESSION = '11111111-1111-4111-8111-111111111111';
const storage = () => {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
};

test('live conversation cards follow the authoritative current conditions after refresh', () => {
  const terms = [{ term_id: 'pose_old' }, { term_id: 'pose_current' }];
  const conditions = [{ term_id: 'pose_current' }];
  assert.deepEqual(filterLiveTerms(terms, conditions, { loaded: true, historical: false }), [terms[1]]);
  assert.deepEqual(filterLiveTerms(terms, [], { loaded: true, historical: false }), []);
  assert.deepEqual(filterLiveTerms(terms, conditions, { loaded: true, historical: true }), terms);
  assert.deepEqual(filterLiveTerms(terms, conditions, { loaded: false, historical: false }), terms);
});

test('a direct or image re-search survives refresh only for the same session and base job', () => {
  const store = storage();
  const term = { term_id: 'pose_ballet', role: 'pose', label_ko: '발레', pins: [] };
  writeLiveReferenceState(store, SESSION, {
    baseJobId: 'job-latest',
    boardView: 'term-results',
    termSearch: { term, loading: false },
    sketchSearches: { pose_ballet: { term: { ...term, pins: [{ pin_id: 'new' }] }, suffix: 'sketch' } },
  });
  assert.equal(readLiveReferenceState(store, SESSION, 'job-latest').termSearch.term.term_id, 'pose_ballet');
  assert.equal(readLiveReferenceState(store, SESSION, 'job-old'), null);
  assert.equal(readLiveReferenceState(store, '22222222-2222-4222-8222-222222222222', 'job-latest'), null);
});

test('invalid, loading, and corrupt snapshots never replace a restored server result', () => {
  const store = storage();
  writeLiveReferenceState(store, SESSION, {
    baseJobId: null, boardView: 'term-results',
    termSearch: { term: { term_id: 'pose_loading' }, loading: true }, sketchSearches: {},
  });
  assert.equal(readLiveReferenceState(store, SESSION, null), null);
  store.setItem(`uhkegryo:live-reference:v1:${SESSION}`, '{broken');
  assert.equal(readLiveReferenceState(store, SESSION, null), null);
});
