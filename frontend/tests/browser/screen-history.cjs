const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],searches=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=process.env.APP_BASE||'http://127.0.0.1:3100';
  await page.route('**/before-app',r=>r.fulfill({contentType:'text/html',body:'<h1>Previous site</h1>'}));
  await page.route('**/api/**',r=>{
   const path=new URL(r.request().url()).pathname;
   if(path==='/api/local/profile')return r.fulfill({json:{persistent:false}});
   if(path==='/api/sessions')return r.fulfill({json:{items:[]}});
   if(path==='/api/term-search'){const b=r.request().postDataJSON();searches.push(b);return r.fulfill({json:{term_id:b.term_id,role:'body',label_ko:'모래시계형',pins:[],reason_codes:['PIN_RESULTS_EMPTY']}});}
   return r.abort();
  });
  await page.goto(base+'/before-app');await page.goto(base);await page.waitForLoadState('networkidle');
  const initial=await page.evaluate(()=>history.length),input=page.getByRole('textbox',{name:'캐릭터 설명',exact:true});
  await input.fill('돌아올 초안');await page.getByRole('button',{name:'용어 선택',exact:true}).click();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/term-search')),page.getByRole('button',{name:'레퍼런스 검색',exact:true}).click()]);
  assert.equal(await page.evaluate(()=>history.length),initial+1,'search must create one real browser entry');
  await page.getByText('검색 결과가 없습니다.',{exact:true}).first().waitFor();
  await page.goBack();await page.locator('.term-graph-scene').waitFor();
  assert.equal(await input.inputValue(),'돌아올 초안');assert.equal(await page.getByRole('button',{name:'선택 1개 입력에 추가',exact:true}).count(),1);
  await page.goForward();await page.getByText('검색 결과가 없습니다.',{exact:true}).first().waitFor();assert.equal(searches.length,1,'forward restores the result without rerunning search');
  await page.goBack();await page.locator('.term-graph-scene').waitFor();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/term-search')),page.getByRole('button',{name:'레퍼런스 검색',exact:true}).click()]);
  await page.getByText('검색 결과가 없습니다.',{exact:true}).first().waitFor();
  await page.reload();await page.waitForLoadState('networkidle');assert(await page.locator('.term-graph-scene').isVisible());
  const afterReload=await page.evaluate(()=>history.length);assert.equal(afterReload,initial+1,'reload must not add a guard entry');
  await page.goBack();await page.locator('.term-graph-scene').waitFor();
  await page.goBack();await page.getByRole('heading',{name:'Previous site',exact:true}).waitFor();
  await page.close();
  const records=await browser.newPage({viewport:{width:1440,height:900}}),reads=[];
  records.on('pageerror',e=>errors.push(e.message));
  const {DEMO_SCENARIOS}=await import('../../lib/portfolio-demo-fixtures.mjs');
  const sidA='11111111-1111-4111-8111-111111111111',sidB='22222222-2222-4222-8222-222222222222';
  const jobs=DEMO_SCENARIOS.map((s,i)=>({...structuredClone(s.job),job_id:`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa${i}`,session_id:i===2?sidB:sidA,request_text:s.request}));
  const sessions=[{session_id:sidA,created_at:'2026-10-19T00:00:00Z',title_terms:[{label_ko:'기록 A'}]},
   {session_id:sidB,created_at:'2026-10-18T00:00:00Z',title_terms:[{label_ko:'기록 B'}]}];
  let accept,agentStarted;const agentGate=new Promise(resolve=>{accept=resolve;}),agentStart=new Promise(resolve=>{agentStarted=resolve;});
  const accepted={...structuredClone(jobs[2]),job_id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',session_id:sidA,request_text:'진행 중 다른 답변을 보는 요청'};
  await records.route('**/api/**',r=>{
   const url=new URL(r.request().url()),path=url.pathname;reads.push(path);
   if(path==='/api/local/profile')return r.fulfill({json:{persistent:true}});
   if(path==='/api/agent'){agentStarted();return agentGate.then(()=>{jobs.push(accepted);return r.fulfill({status:202,json:{job_id:accepted.job_id,poll_after_ms:1}});});}
   if(path==='/api/sessions')return r.fulfill({json:{items:url.searchParams.get('limit')==='1'?[sessions[0]]:sessions}});
   if(path==='/api/term-search'){const body=r.request().postDataJSON(),term=jobs.flatMap(j=>j.result.reference_plan.terms).find(t=>t.term_id===body.term_id);return r.fulfill({json:{...term,pins:[{pin_id:'123456789',pin_url:base,thumbnail_url:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="80" height="120"%3E%3Crect width="80" height="120" fill="pink"/%3E%3C/svg%3E',status:'available'}]}});}
   const session=sessions.find(s=>path===`/api/sessions/${s.session_id}`);if(session)return r.fulfill({json:session});
   if(path.endsWith('/jobs'))return r.fulfill({json:{items:jobs.filter(j=>path.includes(j.session_id)),has_more:false}});
   const job=jobs.find(j=>path===`/api/jobs/${j.job_id}`);if(job)return r.fulfill({json:job});
   return r.abort();
  });
  await records.goto(base);await records.waitForLoadState('networkidle');
  const restoredLength=await records.evaluate(()=>history.length);
  await records.getByRole('button',{name:'← 용어 둘러보기',exact:true}).click();
  assert.equal(await records.evaluate(()=>history.length),restoredLength+1,'initial restored gallery to home is a real transition');
  await records.goBack();await records.locator('.pin-gallery').waitFor();
  const modeName=`포즈 ${jobs[1].result.reference_plan.terms[0].label_ko} 스케치 검색`;
  await Promise.all([records.waitForResponse(r=>r.url().includes('/api/term-search')),records.getByRole('button',{name:modeName,exact:true}).click()]);
  await records.waitForFunction(name=>[...document.querySelectorAll('button')].some(b=>b.getAttribute('aria-label')===name && b.getAttribute('aria-pressed')==='true'),modeName);
  assert.equal(await records.getByRole('button',{name:modeName,exact:true}).getAttribute('aria-pressed'),'true');
  const firstTurn=records.locator('.conversation-turn').filter({hasText:DEMO_SCENARIOS[0].request});
  assert.equal(await firstTurn.locator('.conversation-answer button').count(),0);
  const selectedLength=await records.evaluate(()=>history.length);
  await records.getByRole('button',{name:'UH케그려 기록 열기',exact:true}).filter({visible:true}).first().click();
  await records.getByRole('button',{name:'기록 B',exact:true}).click();
  await records.getByText(DEMO_SCENARIOS[2].request,{exact:true}).waitFor();await records.waitForLoadState('networkidle');
  assert.equal(await records.getByText(DEMO_SCENARIOS[0].request,{exact:true}).count(),0);
  const completedReads=reads.length,switchedLength=await records.evaluate(()=>history.length);
  await records.goBack();await firstTurn.waitFor();
  assert.equal(await records.getByRole('button',{name:modeName,exact:true}).getAttribute('aria-pressed'),'true','session back restores category mode');
  await records.goForward();await records.getByText(DEMO_SCENARIOS[2].request,{exact:true}).waitFor();
  assert.equal(reads.length,completedReads,'session traversal must restore cached results without fetching again');
  await records.goBack();await firstTurn.waitFor();
  assert.equal(await records.evaluate(()=>history.length),switchedLength);
  const liveInput=records.getByRole('textbox',{name:'캐릭터 설명',exact:true});await liveInput.fill(accepted.request_text);
  await records.getByRole('button',{name:'전송',exact:true}).click();await agentStart;
  accept();
  const acceptedTurn=records.locator('.conversation-turn').filter({hasText:accepted.request_text});
  await acceptedTurn.locator('.conversation-answer').waitFor();
  assert.equal(await acceptedTurn.locator('button').count(),0);
  assert.equal(await records.locator('.conversation-answer button').count(),0);
  await records.goBack();await firstTurn.waitFor();
  assert.equal(await records.getByRole('button',{name:modeName,exact:true}).getAttribute('aria-pressed'),'true','request back restores the previous gallery mode');
  await records.goForward();await acceptedTurn.locator('.conversation-answer').waitFor();
  await records.close();
  const pending=await browser.newPage({viewport:{width:1440,height:900}});
  let release,started;const gate=new Promise(resolve=>{release=resolve;}),startedGate=new Promise(resolve=>{started=resolve;});
  pending.on('pageerror',e=>errors.push(e.message));
  await pending.route('**/api/**',async r=>{
   const path=new URL(r.request().url()).pathname;
   if(path==='/api/local/profile')return r.fulfill({json:{persistent:false}});
   if(path==='/api/sessions' && r.request().method()==='POST'){started();await gate;try{return await r.fulfill({status:500,json:{user_message:'late failure'}});}catch{return;}}
   if(path==='/api/sessions')return r.fulfill({json:{items:[]}});return r.abort();
  });
  await pending.goto(base);await pending.waitForLoadState('networkidle');
  const draft=pending.getByRole('textbox',{name:'캐릭터 설명',exact:true});await draft.fill('전송 중 돌아올 초안');
  await pending.getByRole('button',{name:'전송',exact:true}).click();await startedGate;
  const aborted=pending.waitForEvent('requestfailed',{predicate:r=>r.url().endsWith('/api/sessions') && r.method()==='POST'});
  await pending.goBack();await pending.locator('.term-graph-scene').waitFor();await aborted;
  assert.equal(await draft.inputValue(),'전송 중 돌아올 초안');assert.equal(await draft.isEnabled(),true);
  assert.equal(await pending.getByRole('button',{name:'전송',exact:true}).isEnabled(),true);
  release();await pending.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await pending.locator('#request-error').count(),0,'late aborted submission must not change the restored screen');
  await pending.close();
  assert.deepEqual(errors,[]);console.log(JSON.stringify({back:true,forward:true,draftAndSelection:true,noRepeatedSearch:true,reload:true,exitAtHome:true,noAnswerButtons:true,sessionSwitch:true,initialRestoredGallery:true,categoryModeRestored:true,pendingSubmissionCancelled:true,acceptedJobRetained:true,noDuplicateHistory:true,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
