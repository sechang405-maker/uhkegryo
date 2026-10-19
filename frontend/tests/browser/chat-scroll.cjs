const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
const path=require('node:path');

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const checks=[];
 try {for(const mobile of [false,true]) {
  const page=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile});
  const sid='11111111-1111-4111-8111-111111111111',jobs=[],errors=[];let submitted=0;
  page.on('pageerror',error=>errors.push(error.message));
  const longAnswer=Array.from({length:10},(_,i)=>`문단 ${i+1}. 큰 덩어리와 방향을 천천히 살펴보세요. 선의 방향과 접촉면을 확인하면 형태를 더 쉽게 이해할 수 있어요.`).join('\n\n')+
    '\n\n- 큰 형태부터 살펴보세요.\n- 세부 표현은 나중에 더해 보세요.\n\n> 힘들면 잠시 쉬어도 괜찮아요.\n\n마지막 줄도 온전히 읽을 수 있어야 합니다. FINAL-END';
  const makeJob=i=>({job_id:`aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa${i}`,session_id:sid,request_text:'그림 연습 방법 '+i,job_status:'completed',
    result:{agent_status:'drawing_chat',answer_text:longAnswer,reason_codes:[],reference_plan:null}});
  jobs.push(makeJob(0));
  await page.route('**/api/**',route=>{
   const url=new URL(route.request().url()),p=url.pathname;
   if(p==='/api/local/profile')return route.fulfill({json:{persistent:true}});
   if(p==='/api/sessions')return route.fulfill({json:{items:[{session_id:sid,created_at:'2026-10-19T00:00:00Z'}]}});
   if(p==='/api/sessions/'+sid)return route.fulfill({json:{session_id:sid}});
   if(p.endsWith('/jobs'))return route.fulfill({json:{items:jobs,has_more:false}});
   if(p==='/api/agent'){const job=makeJob(++submitted);jobs.push(job);return route.fulfill({status:202,json:{job_id:job.job_id,poll_after_ms:1}});}
   const job=jobs.find(job=>p==='/api/jobs/'+job.job_id);return job?route.fulfill({json:job}):route.abort();
  });
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
  if(mobile)await page.locator('[aria-controls="conversation-panel"]').click();
  await page.locator('.conversation-answer').last().waitFor();
  async function readEnd(label,nativeWheel=false){
   const scroller=page.locator('.panel-top');
   if(nativeWheel){await scroller.evaluate(el=>{el.scrollTop=0;});await scroller.hover();await page.mouse.wheel(0,100000);
    await page.waitForFunction(()=>{const el=document.querySelector('.panel-top');return el.scrollHeight-el.clientHeight-el.scrollTop<2;});
   }else await scroller.evaluate(el=>{el.scrollTop=el.scrollHeight;});
   const actual=await page.evaluate(()=>{
    const scroll=document.querySelector('.panel-top'),answer=document.querySelector('.conversation-thread').lastElementChild.querySelector('.conversation-answer'),composer=document.querySelector('.composer');
    const walker=document.createTreeWalker(answer,NodeFilter.SHOW_TEXT);let node,last;while(node=walker.nextNode())if(node.textContent.trim())last=node;
    const range=document.createRange();range.setStart(last,Math.max(0,last.length-9));range.setEnd(last,last.length);
    const line=range.getBoundingClientRect(),s=scroll.getBoundingClientRect(),a=answer.getBoundingClientRect(),c=composer.getBoundingClientRect();
    const hit=document.elementFromPoint(line.x+line.width/2,line.y+line.height/2);
    return {atEnd:scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop<2,bottomGap:s.bottom-a.bottom,
      inputGap:c.top-a.bottom,lineFullyVisible:line.top>=s.top&&line.bottom<=s.bottom&&line.bottom<c.top,
      readable:!!hit&&answer.contains(hit),composerVisible:c.bottom<=innerHeight+1,noHorizontalOverflow:document.documentElement.scrollWidth<=innerWidth};
   });
   assert.equal(actual.atEnd,true,label+' reaches native scroll end');
   assert.ok(actual.bottomGap>=8,label+' leaves the complete answer clear of the input focus ring: '+JSON.stringify(actual));
   assert.ok(actual.inputGap>=8,label+' must not overlap the composer');
   assert.equal(actual.lineFullyVisible,true,label+' last line must be fully visible');assert.equal(actual.readable,true,label+' last line is unobscured');
   assert.equal(actual.composerVisible,true,label+' composer remains visible');assert.equal(actual.noHorizontalOverflow,true,label+' no horizontal overflow');
   checks.push({mobile,label,...actual});
  }
  await readEnd('one long answer',true);
  await page.locator('#request-text').focus();await readEnd('focused input');
  for(let i=1;i<=2;i++){
   await page.locator('#request-text').fill('더 자세히 알려줘 '+i);await page.locator('.composer-submit').click();
   await page.waitForFunction(count=>document.querySelectorAll('.conversation-answer').length===count,i+1);
   await readEnd('multiple turns '+i,true);
  }
  for(const viewport of mobile?[{width:320,height:568},{width:390,height:500},{width:390,height:844}]:[{width:1024,height:600},{width:844,height:390},{width:1440,height:900}]){
   await page.setViewportSize(viewport);await page.locator('#request-text').focus();await readEnd('resize '+viewport.width+'x'+viewport.height,true);
  }
  if(process.env.SCREENSHOT_DIR)await page.screenshot({path:path.join(process.env.SCREENSHOT_DIR,`chat-scroll-${mobile?'mobile':'desktop'}.png`)});
  if(mobile)await page.locator('[aria-controls="reference-panel"]').click();
  const node=page.locator('.term-graph-node[data-node-id="pose_standing"]');await node.click();
  const query=await page.locator('.recommended-query').innerText();assert.equal(await node.getAttribute('data-selected'),'true');
  if(mobile)await page.locator('[aria-controls="conversation-panel"]').click();
  await page.locator('#request-text').fill('다음 그림도 연습해 볼게요');assert.equal(await page.locator('#request-text').inputValue(),'다음 그림도 연습해 볼게요');
  if(mobile)await page.locator('[aria-controls="reference-panel"]').click();
  assert.equal(await node.getAttribute('data-selected'),'true');assert.equal(await page.locator('.recommended-query').innerText(),query);
  assert.equal(submitted,2);assert.deepEqual(errors,[]);await page.close();
 } console.log(JSON.stringify({desktop:true,mobile:true,longAnswers:true,multipleTurns:true,viewportResize:true,lastLineReadable:true,inputAndGraph:true,checks}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
