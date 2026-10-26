import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { sessionUsage } from '../lib/session-usage.mjs';
const { default: SessionUsageNotice } = await import('../components/SessionUsageNotice.mjs').catch(() => ({}));

test('remaining quota is small text and exhaustion offers a new conversation without hiding content', () => {
  assert.equal(typeof SessionUsageNotice, 'function', 'quota notice component is missing');
  const partial = renderToStaticMarkup(React.createElement(SessionUsageNotice, { usage: { remaining_messages: 1, message_limit: 20, can_submit: true } }));
  assert.match(partial, /1 \/ 20/); assert.doesNotMatch(partial, /<button/);
  const full = renderToStaticMarkup(React.createElement(SessionUsageNotice, { usage: { remaining_messages: 0, message_limit: 20, can_submit: false }, busy: false, onNewSession: () => {} }));
  assert.match(full, /role="status"/); assert.match(full, /새 대화/); assert.match(full, /<button/);
  assert.doesNotMatch(full, /disabled/);
});

test('new conversation is unavailable during submission but existing quota notice stays readable', () => {
  assert.equal(typeof SessionUsageNotice, 'function');
  const full = renderToStaticMarkup(React.createElement(SessionUsageNotice, { usage: { remaining_messages: 0, message_limit: 20, can_submit: false }, busy: true }));
  assert.match(full, /disabled/); assert.match(full, /0 \/ 20/);
});

test('an older focus response cannot undo an accepted twentieth message or affect another session', async () => {
  const source = readFileSync(new URL('../app/page.jsx', import.meta.url), 'utf8');
  const start = source.indexOf('  function applyUsage('), end = source.indexOf('  useEffect(', start);
  const state = { usage: { message_count: 20, can_submit: false } }, releases = [];
  const context = { sessionUsage, uiDemoEnabled: false, sessionIdRef: { current: 'active' }, usageRefreshRef: { current: 0 },
    activeUsageRef: { current: state.usage }, setUsage: value => { state.usage = value; }, setSessions: () => {},
    readConversationUsage: () => new Promise(resolve => releases.push(resolve)) };
  vm.createContext(context); vm.runInContext(source.slice(start, end) + '\nthis.refresh = refreshUsage;', context);
  const pending = context.refresh('active'); releases[0]({ message_count: 19, can_submit: true }); await pending;
  assert.equal(state.usage.message_count, 20);
  const switched = context.refresh('active'); context.sessionIdRef.current = 'different';
  releases[1]({ message_count: 25, can_submit: false }); await switched;
  assert.equal(state.usage.message_count, 20);
});

test('only a successful server-created conversation resets quota and clears the old draft and limit error', async () => {
  const source = readFileSync(new URL('../app/page.jsx', import.meta.url), 'utf8');
  const start = source.indexOf('  async function startNewSession('), end = source.indexOf('  async function removeSession(', start);
  const usageStart = source.indexOf('  function applyUsage('), usageEnd = source.indexOf('  async function refreshUsage(', usageStart);
  const state = { usage: { message_count: 20, can_submit: false }, draft: 'old draft', error: 'limit' }; let release;
  const noop = () => {};
  const context = { sessionUsage, activeUsageRef: { current: state.usage }, sessionIdRef: { current: 'old' },
    setUsage: value => { state.usage = value; }, setSessions: noop, setRequestText: value => { state.draft = value; }, setError: value => { state.error = value; },
    deleteInFlightRef: { current: false }, submitInFlightRef: { current: false }, isSubmitting: false, uiDemoEnabled: false,
    visitScreen: noop, crypto: { randomUUID: () => 'new-navigation' }, screenGenerationRef: { current: 0 }, sessionLoadRef: { current: 0 },
    liveReferenceHydratedRef: { current: false },
    cancelHistory: noop, gallerySelectionRef: { current: { reset: noop } }, setSessionId: noop, setTurns: noop, setJob: noop,
    setTermSearch: noop, setTermGuide: noop, setBoardView: noop, resetSketchSearches: noop, termSearchControllerRef: { current: null },
    previewDialogRef: { current: null }, setPreviewPin: noop, pollerRef: { current: null }, setConversationReady: noop,
    setRestoreError: noop, refreshSessions: noop, setPollError: noop, setMobilePanel: noop, setMenuOpen: noop,
    createConversation: () => new Promise(resolve => { release = resolve; }) };
  vm.createContext(context); vm.runInContext(source.slice(usageStart, usageEnd) + source.slice(start, end) + '\nthis.create = startNewSession;', context);
  const pending = context.create();
  assert.equal(state.usage.message_count, 20, 'pending creation cannot reset quota');
  release({ session_id: 'new', message_count: 0, can_submit: true }); await pending;
  assert.equal(state.usage.message_count, 0); assert.equal(state.draft, ''); assert.equal(state.error, '');
  state.usage = { message_count: 20, can_submit: false }; context.activeUsageRef.current = state.usage;
  context.createConversation = async () => { throw Error('server unavailable'); };
  await context.create();
  assert.equal(context.sessionIdRef.current, 'new', 'failed creation preserves the previous active session');
  assert.equal(state.usage.message_count, 20);
});

test('same-session screen restoration retains known exhausted quota when refresh fails', async () => {
  const source = readFileSync(new URL('../app/page.jsx', import.meta.url), 'utf8');
  const start = source.indexOf('  function restoreScreen('), end = source.indexOf('    if(uiDemoEnabled && snapshot.sessionId)', start);
  const usageStart = source.indexOf('  function applyUsage('), usageEnd = source.indexOf('  useEffect(', usageStart);
  const quota = { message_count: 20, can_submit: false }, state = { usage: quota }, noop = () => {};
  const context = { screenGenerationRef: { current: 1 }, sessionLoadRef: { current: 1 },
    cancelSubmission: noop, cancelHistory: noop, sessionIdRef: { current: 'same' }, pollerRef: { current: null },
    termSearchControllerRef: { current: null }, resetSketchSearches: noop, previewDialogRef: { current: null },
    setPreviewPin: noop, setMenuOpen: noop, activeUsageRef: { current: quota }, setUsage: value => { state.usage = value; },
    uiDemoEnabled: false, sessionUsage, usageRefreshRef: { current: 0 }, setSessions: noop,
    readConversationUsage: async () => { throw Error('GET session unavailable'); } };
  vm.createContext(context); vm.runInContext(source.slice(usageStart, usageEnd) + source.slice(start, end) + '}\nthis.restore = restoreScreen;', context);
  context.restore({ sessionId: 'same', turns: [] });
  await Promise.resolve();
  assert.equal(state.usage?.message_count, 20); assert.equal(context.activeUsageRef.current?.can_submit, false);
});
