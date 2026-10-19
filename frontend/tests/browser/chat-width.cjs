const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});const checks=[];
 try{for(const [width,height] of [[1440,900],[1366,768],[1024,768],[800,600],[761,600],[760,844],[390,844],[320,568]]){
  const page=await browser.newPage({viewport:{width,height}}),sid='11111111-1111-4111-8111-111111111111';
  const answer=Array.from({length:12},()=> '큰 형태부터 단순하게 잡고 선의 방향과 접촉면을 확인해 보세요.').join('\n\n')+'\n\n마지막 줄도 온전히 읽을 수 있어야 합니다. FINAL-END';
  const job={job_id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa0',session_id:sid,request_text:'그림 연습을 알려줘',job_status:'completed',result:{agent_status:'drawing_chat',answer_text:answer}};
  await page.route('**/api/**',r=>{const p=new URL(r.request().url()).pathname;if(p==='/api/local/profile')return r.fulfill({json:{persistent:true}});if(p==='/api/sessions')return r.fulfill({json:{items:[{session_id:sid,created_at:'2026-10-19T00:00:00Z'}]}});if(p==='/api/sessions/'+sid)return r.fulfill({json:{session_id:sid}});if(p.endsWith('/jobs'))return r.fulfill({json:{items:[job],has_more:false}});if(p==='/api/jobs/'+job.job_id)return r.fulfill({json:job});return r.abort();});
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
  if(width<=760)await page.locator('[aria-controls="conversation-panel"]').click();await page.locator('.conversation-answer').waitFor();
  await page.locator('#request-text').fill('다음 그림도 연습해 볼게요');await page.locator('.panel-top').evaluate(el=>{el.scrollTop=el.scrollHeight;});
  const actual=await page.evaluate(()=>{
   const get=s=>document.querySelector(s),rect=s=>{const r=get(s).getBoundingClientRect();return {width:r.width,height:r.height,left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
   const s=get('.panel-top'),a=get('.conversation-answer'),walker=document.createTreeWalker(a,NodeFilter.SHOW_TEXT);let t,last;
   while(t=walker.nextNode())if(t.textContent.trim())last=t;
   const range=document.createRange();range.setStart(last,last.length-9);range.setEnd(last,last.length);
   const line=range.getBoundingClientRect(),hit=document.elementFromPoint(line.x+line.width/2,line.y+line.height/2),input=rect('#request-text'),style=getComputedStyle(get('#request-text'));
   return {panel:rect('.prompt-panel'),scroll:rect('.panel-top'),composer:rect('.composer'),textarea:input,answer:rect('.conversation-answer'),prose:rect('.answer-prose'),
    inputContentWidth:input.width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),inputContentHeight:input.height-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom),
    fontSize:getComputedStyle(get('.answer-prose p')).fontSize,paddingBottom:getComputedStyle(s).paddingBottom,
    lastLineVisible:line.top>=s.getBoundingClientRect().top&&line.bottom<=s.getBoundingClientRect().bottom&&!!hit&&a.contains(hit),horizontalOverflow:document.documentElement.scrollWidth>innerWidth};
  });
  const mobile=width<=760,expected=mobile?width:Math.max(310,Math.min(width*.315,450));
  assert.ok(Math.abs(actual.panel.width-expected)<1,`chat width at ${width}: ${actual.panel.width} expected ${expected}`);
  const proseWidth=expected-(mobile?90:74),inputWidth=expected-(mobile?76:68);
  assert.ok(Math.abs(actual.prose.width-proseWidth)<1,`usable answer width at ${width}: ${actual.prose.width} expected ${proseWidth}`);
  assert.ok(Math.abs(actual.inputContentWidth-inputWidth)<1,`usable input width at ${width}: ${actual.inputContentWidth} expected ${inputWidth}`);
  assert.equal(actual.inputContentHeight,120,'input text height preserved');assert.equal(actual.fontSize,'16px','answer font unchanged');
  assert.equal(actual.panel.height,mobile?height-63:height,'panel height stays unchanged');assert.equal(actual.textarea.height,138,'input height unchanged');
  // Widening may unwrap the existing desktop hint; panel/input heights stay fixed.
  const baselineComposer=!mobile&&width<=1024?239:213;
  assert.ok(actual.composer.height>=213&&actual.composer.height<=baselineComposer,'composer stays within existing one/two-line hint heights at '+width);assert.equal(actual.paddingBottom,'16px');assert.equal(actual.lastLineVisible,true);assert.ok(actual.scroll.bottom-actual.answer.bottom>=8);assert.equal(actual.horizontalOverflow,false);
  if(mobile)await page.locator('[aria-controls="reference-panel"]').click();
  const reference=await page.locator('.reference-board').boundingBox(),query=await page.locator('.recommended-query').boundingBox();
  assert.ok(reference&&reference.width>0,'reference remains available');assert.ok(query&&query.width>100,'query remains usable');assert.ok(query.x>=reference.x&&query.x+query.width<=reference.x+reference.width-8,'query stays inside reference board');
  assert.ok(Math.abs(query.x+query.width/2-width/2)<1,'search remains viewport centered');
  checks.push({width,height,chatWidth:actual.panel.width,proseWidth:actual.prose.width,inputWidth:actual.textarea.width,inputHeight:actual.textarea.height,inputContentWidth:actual.inputContentWidth,inputContentHeight:actual.inputContentHeight,scrollHeight:actual.scroll.height,referenceWidth:reference.width,queryWidth:query.width,lastLineVisible:true});await page.close();
 }console.log(JSON.stringify({checks,mobileUnchanged:true,panelAndInputHeightsUnchanged:true,queryNoOverlap:true,scrollEndPreserved:true}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
