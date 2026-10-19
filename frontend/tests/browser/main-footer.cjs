// Local mocked API regression. APP_BASE, PLAYWRIGHT_MODULE, CHROMIUM_EXECUTABLE are optional.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const errors=[],searches=[];
 try {
  for(const mobile of [false,true]) {
   const context=await browser.newContext({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/**',r=>{
    const path=new URL(r.request().url()).pathname;
    if(path==='/api/local/profile')return r.fulfill({json:{persistent:false}});
    if(path==='/api/sessions')return r.fulfill({json:{items:[]}});
    if(path==='/api/term-search') {const body=r.request().postDataJSON();searches.push(body);return r.fulfill({json:{term_id:body.term_id,role:'body',label_ko:'모래시계형',pins:[],reason_codes:['PIN_RESULTS_EMPTY']}});}
    return r.abort();
   });
   await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');await page.waitForLoadState('networkidle');
   const tools=page.locator('.term-graph-tools'),help=page.locator('.term-graph-help-disclosure');
   assert.equal(await tools.count(),1,'graph controls must be collapsed into one disclosure');
   assert.equal(await tools.getAttribute('open'),null);assert.equal(await page.getByRole('button',{name:'확대',exact:true}).isVisible(),false);
   const summary=tools.locator('summary');
   for(let i=0;i<3;i++) {
    await summary.focus();await page.keyboard.press('Enter');assert.equal(await tools.getAttribute('open'),'');
    await page.keyboard.press('Tab');assert.equal(await page.locator(':focus').getAttribute('aria-label'),'왼쪽으로 회전');
    await summary.focus();await page.keyboard.press('Space');assert.equal(await tools.getAttribute('open'),null);
    assert.equal(await summary.evaluate(e=>e===document.activeElement),true);
   }
   assert.equal(await help.getAttribute('open'),null);
   await help.locator('summary').click();assert.match(await help.innerText(),/방향키.*Tab/);
   await help.locator('summary').click();assert.equal(await help.getAttribute('open'),null);
   assert.equal(await page.getByRole('button',{name:'선택 0개 입력에 추가',exact:true}).count(),0);
   assert.equal(await page.getByText('용어를 고른 뒤 설명을 입력에 추가해 보세요.',{exact:true}).count(),0);
   const scene=page.locator('.term-graph-scene'),before=await scene.getAttribute('data-yaw');
   await scene.focus();await page.keyboard.press('ArrowRight');assert.notEqual(await scene.getAttribute('data-yaw'),before);
   await summary.click();await page.getByRole('button',{name:'회전 초기화',exact:true}).click();assert.equal(await scene.getAttribute('data-yaw'),before);
   const zoom=await scene.getAttribute('data-zoom');await page.getByRole('button',{name:'확대',exact:true}).click();assert(Number(await scene.getAttribute('data-zoom'))>Number(zoom));
   await summary.click();assert.equal(await tools.getAttribute('open'),null);
   await page.getByRole('button',{name:'용어 선택',exact:true}).click();
   await page.getByRole('button',{name:'선택 1개 입력에 추가',exact:true}).click();
   const input=page.getByRole('textbox',{name:'캐릭터 설명',exact:true});await input.waitFor();
   assert.match(await input.inputValue(),/모래시계형/);assert(await input.evaluate(e=>e===document.activeElement));
   assert.equal(await page.locator('#request-hint').isVisible(),!mobile);
   if(mobile)await page.getByRole('button',{name:'레퍼런스',exact:true}).click();
   await page.locator('.term-graph-chips').getByRole('button',{name:'모래시계형 선택 해제',exact:true}).click();
   assert.equal(await page.getByRole('button',{name:'선택 1개 입력에 추가',exact:true}).count(),0);
   await page.getByRole('button',{name:'목록 보기',exact:true}).click();
   const check=page.getByRole('checkbox',{name:'프론트 뷰',exact:true});await check.check();await check.uncheck();
   assert.equal(await page.locator('.term-graph-list input').count(),36);
   await page.getByRole('button',{name:'3D 보기',exact:true}).click();
   await Promise.all([page.waitForResponse(r=>r.url().includes('/api/term-search')),page.getByRole('button',{name:'레퍼런스 검색',exact:true}).click()]);
   assert(searches.length>0);
   if(mobile)await page.getByRole('button',{name:'대화',exact:true}).click();
   await input.fill('가'.repeat(449));assert.equal(await page.locator('#request-count').count(),0);
   await input.fill('가'.repeat(450));assert.equal(await page.locator('#request-count').innerText(),'450 / 500');
   await input.fill('🙂'.repeat(500));assert.equal(await page.locator('#request-count').innerText(),'500 / 500');
   assert.equal(await page.getByRole('button',{name:'전송',exact:true}).isEnabled(),true);
   await input.fill('가'.repeat(501));assert.equal(await input.getAttribute('aria-invalid'),'true');
   assert.match(await page.locator('#request-error').innerText(),/500자 이하/);
   assert.match(await input.getAttribute('aria-describedby'),/request-limit.*request-error/);
   assert.equal(await page.getByRole('button',{name:'전송',exact:true}).isEnabled(),false);
   await input.fill('짧은 설명');assert.equal(await input.getAttribute('aria-invalid'),'false');
   await page.getByRole('heading',{name:'UH케 그릴 건가요?',exact:true}).click();assert.equal(await page.locator('#request-hint').isVisible(),false);
   assert.equal(await page.locator('.prompt-panel .conversation-notice').count(),0);
   await page.getByRole('button',{name:'UH케그려 기록 열기',exact:true}).filter({visible:true}).first().click();
   assert.match(await page.locator('#history-sidebar .conversation-notice').innerText(),/쿠키.*최근 대화/);
   await page.keyboard.press('Escape');assert.equal(await page.locator('#history-sidebar').getAttribute('open'),null);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({desktop:true,mobile:true,disclosures:true,keyboardFocus:true,selection:true,search:true,counterAndErrors:true,historyNotice:true,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
