import { DEMO_SCENARIOS, matchDemoScenario } from './portfolio-demo-fixtures.mjs';

export const DEMO_SESSION_KEY = 'uh-studio-portfolio-sessions-v1';
const id = () => `demo-${globalThis.crypto.randomUUID()}`;
const validId = value => typeof value === 'string' && /^demo-[\w-]{1,80}$/.test(value);
const hydrate = turn => {
  const fixture = DEMO_SCENARIOS.find(item => item.id === turn.fixtureId);
  return { id: turn.id, fixtureId: fixture.id, request: fixture.request, job: fixture.job, demo: true };
};
export function createDemoSessionStore(storage) {
  let sessions = [], active, storageFailed = false;
  function current() {
    const session = sessions.find(item => item.session_id === active);
    return { ...session, turns: session.turns.map(hydrate) };
  }
  function save() {
    let budget = 50;
    sessions = sessions.slice(0, 10).map(session => {
      const turns = budget ? session.turns.slice(-budget) : [];
      budget -= turns.length;
      return { ...session, turns };
    });
    try { storage.setItem(DEMO_SESSION_KEY, JSON.stringify({ active, sessions })); }
    catch { storageFailed = true; }
  }
  function create() {
    const session = {session_id:id(),created_at:new Date().toISOString(),turns:[]};
    sessions.unshift(session); active = session.session_id; save(); return current();
  }
  try {
    const raw = storage.getItem(DEMO_SESSION_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      if (!Array.isArray(saved.sessions) || !saved.sessions.length || saved.sessions.length > 10
        || new Set(saved.sessions.map(s => s.session_id)).size !== saved.sessions.length
        || saved.sessions.reduce((n,s) => n + (s.turns?.length || 0),0) > 50) throw Error('invalid demo sessions');
      sessions = saved.sessions.map(s => {
        if (!validId(s.session_id) || typeof s.created_at !== 'string' || Number.isNaN(Date.parse(s.created_at))
          || !Array.isArray(s.turns) || new Set(s.turns.map(t=>t.id)).size !== s.turns.length) throw Error('invalid demo session');
        const turns = s.turns.map(t => {
          const fixture = DEMO_SCENARIOS.find(item => item.id === t.fixtureId);
          if (!validId(t.id) || !fixture || t.request !== fixture.request || t.answer !== fixture.job.result.answer_text) throw Error('invalid demo turn');
          return { id:t.id, fixtureId:fixture.id, request:fixture.request, answer:fixture.job.result.answer_text };
        });
        return {session_id:s.session_id,created_at:s.created_at,turns};
      });
      active = saved.active;
      if (!sessions.some(s => s.session_id === active)) throw Error('invalid active demo session');
    }
  } catch { sessions = []; storageFailed = true; }
  if (!sessions.length) {
    create();
    const fixture = DEMO_SCENARIOS[0];
    sessions[0].turns.push({id:id(),fixtureId:fixture.id,request:fixture.request,answer:fixture.job.result.answer_text});
    save();
  }
  return {
    current, create,
    remove(sessionId) {
      sessions = sessions.filter(s => s.session_id !== sessionId);
      if (!sessions.length) return create();
      if (active === sessionId) active = sessions[0].session_id;
      save(); return current();
    },
    get storageFailed() { return storageFailed; },
    list: () => sessions.map(({session_id,created_at})=>({session_id,created_at})),
    select(sessionId) {
      const selected = sessions.find(s => s.session_id === sessionId);
      if (!selected) return null;
      sessions = [selected,...sessions.filter(s=>s!==selected)]; active=sessionId; save(); return current();
    },
    submit(text) {
      const fixture = matchDemoScenario(text);
      if (!fixture) return null;
      const turn = {id:id(),fixtureId:fixture.id,request:fixture.request,answer:fixture.job.result.answer_text};
      sessions.find(s=>s.session_id===active).turns.push(turn); save(); return hydrate(turn);
    },
  };
}
