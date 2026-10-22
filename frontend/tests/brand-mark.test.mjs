import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source=readFileSync(new URL('../components/HistoryDrawer.jsx',import.meta.url),'utf8');
const css=readFileSync(new URL('../app/globals.css',import.meta.url),'utf8');

test('the selected original logo keeps the accessible history button',()=>{
 assert.match(source,/aria-label=/);
 assert.match(source,/<img className="brand-mark-art" src="\/uhkegryo-logo-3\.png" alt=""/);
 assert.doesNotMatch(source,/className="brand-mark"[^>]*>UH<\/span>/);
 assert.match(css,/\.brand-mark\s*\{[^}]*background:\s*transparent[^}]*color:\s*var\(--accent\)/s);
 assert.match(css,/\.brand-mark-art\s*\{[^}]*width:\s*100%[^}]*height:\s*100%[^}]*object-fit:\s*contain/s);
});

test('the rejected reconstructed SVG is no longer rendered',()=>{
 assert.doesNotMatch(source,/brand-mark-frame|brand-mark-monogram|brand-mark-pencil/);
 assert.doesNotMatch(css,/\.brand-mark-frame|\.brand-mark-monogram|\.brand-mark-pencil/);
});
