import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

test('assistant answer cards use the shared brand accent for their border', () => {
  const rule = css.match(/\.conversation-answer\s*\{([^}]*)\}/s)?.[1] ?? '';
  assert.match(rule, /border:\s*2px solid var\(--accent\)/);
});
