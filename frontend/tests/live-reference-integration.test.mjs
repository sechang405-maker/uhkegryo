import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync(new URL('../app/page.jsx', import.meta.url), 'utf8');

test('refresh restoration filters live job cards and restores the saved direct-search view', () => {
  assert.match(page, /filterLiveTerms\([\s\S]*renderedResultTerms\(job, turns, referenceJob\)[\s\S]*historical: Boolean\(historyTurnId\)/);
  assert.match(page, /gallerySelectionRef\.current\.live\([\s\S]*restoreLiveReference\(restored\)/);
  assert.match(page, /writeLiveReferenceState\(browserSessionStorage\(\), sessionId/);
});

test('condition removal clears matching direct and image searches without deleting history', () => {
  const start = page.indexOf('  async function removeCondition(termId)');
  const end = page.indexOf('  function browserSessionStorage()', start);
  const source = page.slice(start, end);
  assert.match(source, /setSketchSearches/);
  assert.match(source, /setTermSearch\(null\)/);
  assert.match(source, /setBoardView\('results'\)/);
  assert.doesNotMatch(source, /setTurns\(|deleteConversation|setHistoryPage/);
});
