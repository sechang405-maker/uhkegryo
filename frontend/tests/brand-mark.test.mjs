import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source=readFileSync(new URL('../components/HistoryDrawer.jsx',import.meta.url),'utf8');
const css=readFileSync(new URL('../app/globals.css',import.meta.url),'utf8');

test('the UH logo letters are transparent cutouts without changing the accessible button',()=>{
 assert.match(source,/aria-label=/);
 assert.match(source,/<svg className="brand-mark-art"[^>]*aria-hidden="true"/);
 assert.match(source,/fillRule="evenodd"/);
 assert.doesNotMatch(source,/className="brand-mark"[^>]*>UH<\/span>/);
 assert.match(css,/\.brand-mark\s*\{[^}]*background:\s*transparent[^}]*color:\s*var\(--accent\)/s);
 assert.match(css,/\.brand-mark-art\s*\{[^}]*width:\s*100%[^}]*height:\s*100%/s);
});

test('the selected logo keeps the crop frame and pencil silhouette at header size',()=>{
 assert.match(source,/className="brand-mark-frame"/);
 assert.match(source,/className="brand-mark-monogram"/);
 assert.match(source,/className="brand-mark-pencil"/);
 assert.match(css,/\.brand-mark-frame\s*\{[^}]*stroke-linecap:round[^}]*stroke-linejoin:round/s);
 assert.doesNotMatch(source,/<rect[^>]*className="brand-mark-background"/);
});
