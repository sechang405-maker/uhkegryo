const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
 const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const checks=[];
 try { for(const mobile of [false,true]) {
  const page=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile}),errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  const {DEMO_SCENARIOS}=await import('../../lib/portfolio-demo-fixtures.mjs');
  const sid='11111111-1111-4111-8111-111111111111';
  const id=n=>'aaaaaaaa-aaaa-4aaa-8aaa-'+String(n).padStart(12,'0');
  const original={...structuredClone(DEMO_SCENARIOS[0].job),job_id:id(0),session_id:sid,request_text:'이전 레퍼런스'};
  const base={...(original.result.reference_plan.terms.find(term=>term.role==='pose')||original.result.reference_plan.terms[0]),role:'pose',
   plain_meaning_ko:'인물이 앉거나 선 자세의 무게와 지지점을 관찰해 보세요.',
   pins:[{pin_id:'123456789',pin_url:'https://www.pinterest.com/pin/123456789/',status:'available',thumbnail_url:'data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="220"><rect width="160" height="220" fill="pink"/></svg>').toString('base64')}]};
  const group={group_id:id(1),source_job_id:id(1),session_id:sid,source_answer:'1. 서 있는 인물\n\n2. 앉은 인물',candidates:[
   {candidate_id:id(101),ordinal:1,name:'서 있는 인물',source_quote:'서 있는 인물',terms:[{role:'pose',term_id:'pose_standing',evidence:['서 있는 인물'],confidence:1,source_job_id:null}],unsupported_constraints:[]},
   {candidate_id:id(102),ordinal:2,name:'앉은 인물',source_quote:'앉은 인물',terms:[{role:'pose',term_id:'pose_sitting',evidence:['앉은 인물'],confidence:1,source_job_id:null}],unsupported_constraints:[]}]};
  const turn=(n,text,result)=>({job_id:id(n),session_id:sid,request_text:text,job_status:'completed',result});
  const adoption=(status='searched')=>({group_id:group.group_id,source_job_id:group.source_job_id,candidate_id:group.candidates[1].candidate_id,request_text:'2번인데 정면으로 찾아줘',source_quote:'앉은 인물',status,search_term_ids:['pose_sitting']});
  const reference=(n,term,query,answer,failed=false)=>turn(n,'레퍼런스 검색',{agent_status:failed?'partial_result':'success',answer_text:answer,
   recommendation_adoption:adoption(failed?'search_failed':'searched'),reason_codes:failed?['PIN_SEARCH_UNAVAILABLE']:[],
   reference_plan:{terms:[{...structuredClone(base),term_id:term,label_ko:term==='pose_sitting'?'앉은 자세':'서 있는 자세',recommended_search_query:query,
    search_url:'https://kr.pinterest.com/search/pins/?'+new URLSearchParams({q:query}),...(failed?{pins:[],reason_codes:['PIN_SEARCH_UNAVAILABLE'],search_failure:'temporary',retryable:true}:{})}],unresolved_roles:[]}});
  const replies=[
   turn(1,'그릴 아이디어를 추천해줘',{agent_status:'drawing_chat',answer_text:'1. 서 있는 인물\n\n2. 앉은 인물',recommendation_group:group}),
   turn(2,'방금 추천한 걸로 찾아줘',{agent_status:'drawing_chat',answer_text:'1번 서 있는 인물과 2번 앉은 인물 중 어느 후보로 찾을까요?',recommendation_group:group}),
   reference(3,'pose_sitting','seated figure reference drawing','2번 앉은 인물로 찾았어요.'),
   reference(4,'pose_sitting','seated frontal figure reference drawing','2번 앉은 인물을 정면으로 바꾸어 찾았어요.'),
   reference(5,'pose_standing','standing figure reference drawing','추천한 후보의 검색에 실패했어요. 기존 결과를 유지했어요.',true),
   reference(6,'pose_standing','standing figure reference drawing','같은 후보로 다시 찾았어요.'),
   reference(7,'pose_sitting','seated figure reference drawing','앉은 인물을 추천해 바로 찾았어요.'),
  ];
  const jobs=[original];let index=0,lastReference=original;
  await page.route('**/api/**',route=>{const p=new URL(route.request().url()).pathname;
   if(p==='/api/local/profile')return route.fulfill({json:{persistent:true}});
   if(p==='/api/sessions')return route.fulfill({json:{items:[{session_id:sid,created_at:'2026-10-19T00:00:00Z'}]}});
   if(p==='/api/sessions/'+sid)return route.fulfill({json:{session_id:sid,created_at:'2026-10-19T00:00:00Z'}});
   if(p.endsWith('/jobs'))return route.fulfill({json:{items:jobs,reference_item:lastReference,has_more:false}});
   if(p==='/api/agent'){requests.push(route.request().postDataJSON());const reply=replies[index++];assert.ok(reply,'unexpected extra request');jobs.push(reply);if(reply.result.agent_status==='success')lastReference=reply;return route.fulfill({status:202,json:{job_id:reply.job_id,poll_after_ms:1}});}
   const job=jobs.find(job=>p==='/api/jobs/'+job.job_id);if(job)return route.fulfill({json:job});return route.abort();
  });
  await page.route('https://**/*',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="120"><rect width="80" height="120" fill="pink"/></svg>'}));
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');await page.locator('.pin-gallery').waitFor({state:'attached'});
  const board=()=>page.locator('.pin-gallery').evaluate(el=>el.textContent);
  const query=()=>page.locator('.recommended-query code').textContent();
  const before=await board(),beforeQuery=await query();
  async function send(text,answer){if(mobile)await page.locator('[aria-controls="conversation-panel"]').click();await page.locator('#request-text').fill(text);await page.getByRole('button',{name:'전송',exact:true}).click();await page.waitForFunction(value=>[...document.querySelectorAll('.conversation-answer')].some(el=>el.textContent.includes(value)),answer.includes('\n')?'서 있는 인물':answer);await page.waitForFunction(()=>!document.querySelector('#request-text').disabled);assert.equal(await page.locator('.conversation-answer button').count(),0);}
  await send('그릴 아이디어를 추천해줘',replies[0].result.answer_text);assert.equal(await board(),before);assert.equal(await query(),beforeQuery);
  await send('방금 추천한 걸로 찾아줘',replies[1].result.answer_text);assert.equal(await board(),before);
  await send('2',replies[2].result.answer_text);assert.equal(await query(),'seated figure reference drawing');
  await send('2번인데 정면으로 찾아줘',replies[3].result.answer_text);assert.equal(await query(),'seated frontal figure reference drawing');
  assert.equal(new URL(await page.getByRole('link',{name:'Pinterest에서 검색',exact:true}).getAttribute('href')).searchParams.get('q'),await query());
  const selected=await board(),selectedQuery=await query();
  await send('다른 후보로 찾아줘',replies[4].result.answer_text);assert.equal(await board(),selected);assert.equal(await query(),selectedQuery);
  await page.reload();await page.locator('.pin-gallery').waitFor({state:'attached'});assert.equal(await board(),selected);assert.equal(await query(),selectedQuery);
  await send('같은 후보로 다시 찾아줘',replies[5].result.answer_text);assert.equal(await query(),'standing figure reference drawing');
  await send('추천해서 바로 찾아줘',replies[6].result.answer_text);assert.equal(await query(),'seated figure reference drawing');
  assert.equal(requests.length,7);assert.equal(requests[2].request_text,'2');assert.ok(requests.every(request=>request.session_id===sid));assert.deepEqual(errors,[]);
  assert.equal(await page.locator('.composer-submit').getAttribute('aria-label'),'전송');assert.equal((await page.locator('.composer-submit').textContent()).trim(),'');
  if(process.env.SCREENSHOT_DIR){if(mobile)await page.locator('[aria-controls="reference-panel"]').click();await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,`recommendation-${mobile?'mobile':'desktop'}.png`)});}
  checks.push({mobile,numberedText:true,noAnswerButtons:true,ambiguityPreservesGallery:true,bareNumber:true,overrideQuery:true,failureAndReloadPreserveGallery:true,explicitRetry:true,oneShot:true,submissions:requests.length});await page.close();
 }console.log(JSON.stringify({checks}));}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
