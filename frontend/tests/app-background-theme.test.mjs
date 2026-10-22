import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css=readFileSync(new URL('../app/globals.css',import.meta.url),'utf8');

test('the whole app uses four crisp pastel fields separated by 45 degree boundaries',()=>{
 assert.match(css,/--app-background:\s*linear-gradient\(45deg,/);
 assert.match(css,/#d6ecec\s+0\s+25%,\s*#f3ded0\s+25%\s+50%,\s*#e8dff2\s+50%\s+75%,\s*#ddecd9\s+75%\s+100%/i);
 assert.match(css,/body\s*\{[^}]*background:\s*var\(--app-background\)/s);
 assert.match(css,/\.workspace\s*\{[^}]*background:\s*var\(--app-background\)/s);
});

test('large graph and chat regions remain transparent while reading surfaces stay light',()=>{
 assert.match(css,/\.reference-board\s*\{[^}]*background:\s*transparent/s);
 assert.match(css,/\.prompt-panel\s*\{[^}]*background:\s*transparent/s);
 assert.match(css,/\.term-graph-scene\s*\{[^}]*background:\s*transparent/s);
 assert.match(css,/--surface:\s*#fbfaf7/i);
 assert.match(css,/--text:\s*#20242a/i);
});
