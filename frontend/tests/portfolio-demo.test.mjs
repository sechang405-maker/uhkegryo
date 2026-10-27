import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';

test('production demo is opt-in and never creates an API rewrite', () => {
  const script = "const c=(await import('./next.config.mjs')).default; const d=await import('./lib/demo-job.mjs'); console.log(JSON.stringify({demo:d.uiDemoEnabled,rewrites:await c.rewrites()}))";
  const run = (mode, gateway = '0') => JSON.parse(execFileSync(process.execPath, ['--input-type=module','-e',script], {
    cwd: new URL('..', import.meta.url), encoding:'utf8', stdio:'pipe', env:{...process.env,NODE_ENV:'production',NEXT_PUBLIC_UI_DEMO:mode,PORTFOLIO_GATEWAY_PROXY:gateway,AGENT_API_ORIGIN:'http://127.0.0.1:9999'},
  }));
  assert.deepEqual(run('1'),{demo:true,rewrites:[]});
  assert.equal(run('0').demo,false);
  assert.equal(run('').rewrites.beforeFiles[0].destination,'http://127.0.0.1:9999/api/:path*');
  assert.deepEqual(run('0', '1').rewrites, []);
  assert.throws(()=>run('typo'));
  assert.throws(()=>run('0', 'typo'));
});

test('portfolio fixtures match exact inputs and never contain remote images', async () => {
  const { DEMO_SCENARIOS, matchDemoScenario, demoTerm } = await import('../lib/portfolio-demo-fixtures.mjs');
  assert.equal(DEMO_SCENARIOS.length,3);
  for(const item of DEMO_SCENARIOS) {
    assert.equal(matchDemoScenario(' '+item.request+' ').id,item.id);
    assert.ok(item.job.result.reference_plan.terms.length);
    assert.ok(item.job.result.reference_plan.terms.every(t=>t.pins.length===0));
    assert.doesNotMatch(JSON.stringify(item),/thumbnail_url|pinimg|api_key/i);
  }
  assert.equal(matchDemoScenario('unknown'),null);
  assert.equal(demoTerm('unknown'),null);
});

test('local demo sessions restore galleries, reject unknown input and bound text storage', async () => {
  const {createDemoSessionStore,DEMO_SESSION_KEY}=await import('../lib/portfolio-demo-sessions.mjs');
  const {DEMO_SCENARIOS}=await import('../lib/portfolio-demo-fixtures.mjs');
  let raw=null;
  const storage={getItem:()=>raw,setItem:(key,value)=>{assert.equal(key,DEMO_SESSION_KEY);raw=value;}};
  const store=createDemoSessionStore(storage);
  const first=store.current();
  assert.equal(store.submit('unknown'),null);
  for(let i=0;i<55;i++)store.submit(DEMO_SCENARIOS[i%3].request);
  const second=store.create();
  assert.equal(store.current().turns.length,0);
  store.submit(DEMO_SCENARIOS[2].request);
  store.select(first.session_id);
  assert.notEqual(first.session_id,second.session_id);
  assert.ok(store.current().turns.length);
  const restored=createDemoSessionStore(storage);
  assert.equal(restored.current().session_id,first.session_id);
  assert.ok(restored.current().turns.at(-1).job.result.reference_plan.terms.length);
  assert.ok(JSON.parse(raw).sessions.reduce((n,s)=>n+s.turns.length,0)<=50);
  assert.doesNotMatch(raw,/reference_plan|pin_url|thumbnail_url|cookie|https:/);
  assert.equal(store.select('server-session'),null);
});

test('blocked or corrupt storage recovers in memory without a network fallback', async () => {
  const {createDemoSessionStore}=await import('../lib/portfolio-demo-sessions.mjs');
  const {DEMO_SCENARIOS}=await import('../lib/portfolio-demo-fixtures.mjs');
  for(const storage of [{getItem(){throw Error('blocked')},setItem(){throw Error('blocked')}},
    {getItem:()=>'{broken',setItem(){}}]) {
    const store=createDemoSessionStore(storage);
    assert.equal(store.storageFailed,true);
    assert.ok(store.submit(DEMO_SCENARIOS[0].request));
    assert.equal(store.current().turns.at(-1).demo,true);
  }
});

test('demo storage caps sessions and rejects injected gallery content', async () => {
  const {createDemoSessionStore}=await import('../lib/portfolio-demo-sessions.mjs');
  let raw;
  const storage={getItem:()=>raw,setItem:(_,value)=>{raw=value;}};
  const store=createDemoSessionStore(storage);
  for(let i=0;i<12;i++)store.create();
  assert.equal(store.list().length,10);
  const saved=JSON.parse(raw);
  saved.sessions[0].turns=[{id:'demo-injected',fixtureId:'remote-url',request:'secret',answer:'forged'}];
  raw=JSON.stringify(saved);
  const restored=createDemoSessionStore(storage);
  assert.equal(restored.storageFailed,true);
  assert.equal(restored.current().turns[0].fixtureId,'demo-hourglass');
  assert.doesNotMatch(raw,/remote-url|secret|forged/);
});
