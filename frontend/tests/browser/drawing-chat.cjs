const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try { for(const mobile of [false,true]) {
  const page=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile}),calls=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const {DEMO_SCENARIOS}=await import('../../lib/portfolio-demo-fixtures.mjs');
  const sid='11111111-1111-4111-8111-111111111111';
  const reference={...structuredClone(DEMO_SCENARIOS[0].job),job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa0',session_id:sid,request_text:'saved reference'};
  const thumbnail='data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120"><rect width="80" height="120" fill="pink"/></svg>').toString('base64');
  reference.result.reference_plan.terms=reference.result.reference_plan.terms.map(term=>({...term,pins:[{pin_id:'123456789',pin_url:'https://www.pinterest.com/pin/123456789/',thumbnail_url:thumbnail,status:'available'}]}));
  const chat=(n,status,text)=>({job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa'+n,session_id:sid,request_text:'chat '+n,job_status:'completed',result:{agent_status:status,answer_text:text,...(status==='needs_clarification'?{clarifying_question:text,clarification_choices:[{label:'choice',request_text:'choice'}]}:{})}});
  const initial=chat(1,'drawing_chat','I remember your drawing.');
  const replies=[chat(2,'drawing_chat','Try a softer silhouette.'),chat(3,'needs_clarification','Do you mean the silhouette we discussed?'),{...reference,...structuredClone(DEMO_SCENARIOS[1].job),job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4',request_text:'find references',result:{...structuredClone(DEMO_SCENARIOS[1].job.result),answer_text:'Here are the requested references.'}}];
  const jobs=[reference,initial];let submitted=0, releaseAgent=null, agentStarted=null;
  await page.route('**/api/**',r=>{const url=new URL(r.request().url()),p=url.pathname;calls.push(p);
   if(p==='/api/local/profile')return r.fulfill({json:{persistent:true}});
   if(p==='/api/sessions')return r.fulfill({json:{items:[{session_id:sid,created_at:'2026-10-19T00:00:00Z'}]}});
   if(p==='/api/sessions/'+sid)return r.fulfill({json:{session_id:sid,created_at:'2026-10-19T00:00:00Z'}});
   if(p.endsWith('/jobs'))return r.fulfill({json:{items:jobs,reference_item:reference,has_more:false}});
   if(p==='/api/term-search'){const body=r.request().postDataJSON();return r.fulfill({json:{term_id:body.term_id,role:'pose',label_ko:'Navigation pose',recommended_search_query:'standing pose reference drawing',pins:[],reason_codes:['PIN_RESULTS_EMPTY']}});}
   if(p==='/api/agent'){const reply=replies[submitted++];jobs.push(reply);if(agentStarted)agentStarted();return new Promise(resolve=>{releaseAgent=()=>resolve(r.fulfill({status:202,json:{job_id:reply.job_id,poll_after_ms:1}}));});}
   const job=jobs.find(j=>p==='/api/jobs/'+j.job_id);if(job)return r.fulfill({json:job});return r.abort();
  });
  await page.route('https://**/*',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120"><rect width="80" height="120" fill="pink"/></svg>'}));
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');await page.waitForLoadState('networkidle');
  assert.equal(await page.locator('.conversation-answer button').count(),0,'answers must have no attached controls, including restored reference answers');
  const board=()=>page.locator('.pin-gallery').evaluate(el=>JSON.stringify([...el.querySelectorAll('.pin-gallery-row')].map(row=>({id:row.dataset.galleryTermId,text:row.textContent,pins:[...row.querySelectorAll('img')].map(img=>({src:img.getAttribute('src'),alt:img.alt})),modes:[...row.querySelectorAll('.sketch-search-button')].map(button=>button.getAttribute('aria-pressed'))}))));const saved=await board();
  async function send(text,answer,explicit=false){
   if(mobile)await page.locator('.mobile-workspace-nav [aria-controls="conversation-panel"]').click();
   await page.locator('#request-text').fill(text);const started=new Promise(resolve=>{agentStarted=resolve;});
   await page.locator('.composer-submit').click();await started;
   assert.equal(await page.locator('.workspace').getAttribute('data-mobile-panel'),'conversation','sending a chat keeps its conversation visible');
   assert.equal(await page.locator('.pin-gallery,.term-graph-scene').count(),1,'pending chat must retain the board or graph');
   releaseAgent();await page.getByText(answer,{exact:true}).waitFor({state:explicit&&mobile?'attached':'visible'});
   await page.waitForFunction(()=>!document.querySelector('#request-text').disabled);
  }
  await send('How can I improve it?','Try a softer silhouette.');assert.equal(await board(),saved);
  await send('What about that part?','Do you mean the silhouette we discussed?');assert.equal(await board(),saved);
  assert.equal(await page.locator('.conversation-answer button').count(),0);assert.equal(calls.filter(p=>p==='/api/term-search').length,0);
  await send('Find references for it','Here are the requested references.',true);assert.equal(submitted,3);assert.notEqual(await board(),saved,'explicit search replaces the board');assert.equal(await page.locator('.conversation-answer button').count(),0);
  await page.goBack();await page.getByText('Do you mean the silhouette we discussed?',{exact:true}).waitFor();assert.equal(await board(),saved);
  await page.goForward();await page.getByText('Here are the requested references.',{exact:true}).waitFor({state:'attached'});assert.equal(submitted,3);
  // A plain chat on the graph keeps the chosen query and graph selection.
  if(mobile)await page.locator('.mobile-workspace-nav [aria-controls="reference-panel"]').click();await page.locator('.gallery-back-button').click();
  await page.locator('.term-graph-node[data-node-id="pose_standing"]').click();
  const query=await page.locator('.recommended-query code').textContent();
  replies.push(chat(5,'drawing_chat','Keep that pose in mind.'));
  await send('Remember that pose','Keep that pose in mind.');
  assert.equal(await page.locator('.term-graph-node[data-selected="true"]').count(),1);assert.equal(await page.locator('.recommended-query code').textContent(),query);
  // A graph search while POST is pending must remain selected when that old request completes.
  replies.push({...reference,job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6',request_text:'delayed reference'});
  if(mobile)await page.locator('.mobile-workspace-nav [aria-controls="conversation-panel"]').click();
  await page.locator('#request-text').fill('Find references, but I may browse meanwhile');
  const started=new Promise(resolve=>{agentStarted=resolve;});await page.locator('.composer-submit').click();await started;
  if(mobile)await page.locator('.mobile-workspace-nav [aria-controls="reference-panel"]').click();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/term-search')),page.locator('.term-graph-actions button').last().click()]);
  if(mobile)await page.locator('.mobile-workspace-nav [aria-controls="reference-panel"]').click();
  await page.locator('[data-gallery-term-id="pose_standing"]').waitFor();
  const navigationBoard=await board(),navigationQuery=await page.locator('.recommended-query code').textContent();
  releaseAgent();await page.waitForFunction(()=>!document.querySelector('#request-text').disabled);
  assert.equal(await board(),navigationBoard,'a POST accepted after navigation must not replace the chosen term search');
  assert.equal(await page.locator('.recommended-query code').textContent(),navigationQuery);
  assert.equal(await page.locator('#request-text').inputValue(),'Find references, but I may browse meanwhile');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.deepEqual(errors,[]);await page.close();
 } console.log(JSON.stringify({desktop:true,mobile:true,savedReferenceRestored:true,chatAndClarificationPreserveBoard:true,noAnswerButtons:true,explicitSearch:true,backForward:true,graphSelectionPreserved:true,pendingPostNavigationPreserved:true}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
