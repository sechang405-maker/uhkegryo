const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const errors=[];
 try{
  for(const mobile of [false,true]) {
   const page=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile,reducedMotion:'reduce'}),calls=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/**',r=>{const p=new URL(r.request().url()).pathname;
    if(p==='/api/local/profile')return r.fulfill({json:{persistent:false}});
    if(p==='/api/sessions')return r.fulfill({json:{items:[]}});
    calls.push(p);
    if(p==='/api/term-search'){const body=r.request().postDataJSON();return r.fulfill({json:{term_id:body.term_id,role:'body',label_ko:'모래시계형',pins:[],reason_codes:['PIN_RESULTS_EMPTY']}});}
    return r.abort();});
   await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');await page.waitForLoadState('networkidle');
   await page.waitForTimeout(100); // Let ResizeObserver-driven graph safe areas settle before geometry assertions.
    const ensure3D=async()=>{
     await page.locator('.term-graph-scene,.term-graph-list').first().waitFor();
     if(await page.locator('.term-graph-list').count()) await page.locator('.term-graph-view-toggle > button').click();
     await page.locator('.term-graph-scene').waitFor();
    };
   await ensure3D();
   const readQuery=()=>page.locator('[aria-label="추천 검색어"]').innerText();
   const defaultQuery=await readQuery(),scene=page.locator('.term-graph-scene');
   const geometry=()=>page.locator('.term-graph-node,.term-graph-category').evaluateAll(es=>es.map(e=>({
    id:e.dataset.nodeId,worldX:e.dataset.worldX,worldY:e.dataset.worldY,worldZ:e.dataset.worldZ,depth:e.dataset.depth,
   })));
   const before=await geometry(),yaw=await scene.getAttribute('data-yaw'),pitch=await scene.getAttribute('data-pitch'),zoom=await scene.getAttribute('data-zoom');
   if(!mobile)await page.getByRole('textbox',{name:'캐릭터 설명'}).fill('내가 직접 작성한 초안');
   const body=page.locator('.term-graph-node[data-node-id="body_hourglass"]'),pose=page.locator('.term-graph-node[data-node-id="pose_standing"]');
   await pose.click();assert.match(await readQuery(),/standing/,'node selection immediately updates the Pinterest query');
   await body.click();assert.match(await readQuery(),/hourglass.*standing/);
   const link=page.getByRole('link',{name:'Pinterest에서 검색',exact:true});assert.equal(new URL(await link.getAttribute('href')).searchParams.get('q'),await readQuery());
   await pose.click();assert.match(await readQuery(),/hourglass/);assert.doesNotMatch(await readQuery(),/standing/);
   await body.click();assert.equal(await readQuery(),defaultQuery);
   await pose.evaluate(e=>{e.click();e.click();e.click();});await page.waitForFunction(()=>document.querySelector('[aria-label="추천 검색어"]')?.textContent.includes('standing'));
   assert.equal(await page.locator('.term-graph-node[data-selected="true"]').count(),1);
   assert.deepEqual(await geometry(),before);assert.equal(await scene.getAttribute('data-yaw'),yaw);assert.equal(await scene.getAttribute('data-pitch'),pitch);assert.equal(await scene.getAttribute('data-zoom'),zoom);
   await page.getByRole('button',{name:'목록 보기',exact:true}).click();
   await page.getByRole('checkbox',{name:'프론트 뷰',exact:true}).check();assert.match(await readQuery(),/standing.*front view/);
   await page.getByRole('checkbox',{name:'프론트 뷰',exact:true}).uncheck();assert.doesNotMatch(await readQuery(),/front view/);
   await page.getByRole('checkbox',{name:'모래시계형',exact:true}).check();const combined=await readQuery();assert.match(combined,/hourglass.*standing/);
   assert.deepEqual(calls,[],'selection must not run API searches');
   const centered=async()=>{const r=await page.locator('.recommended-query').boundingBox(),width=await page.evaluate(()=>innerWidth);assert(Math.abs(r.x+r.width/2-width/2)<2,'Pinterest search area must be centered in the window');assert(r.x>=0&&r.x+r.width<=width);const logo=page.locator('.desktop-history-logo');if(await logo.isVisible()){const l=await logo.boundingBox();assert(l.x+l.width<=r.x,'search area must not overlap the history logo');}};
   await centered();if(!mobile){await page.setViewportSize({width:800,height:900});await centered();await page.setViewportSize({width:1440,height:900});}else{await page.setViewportSize({width:320,height:844});await centered();await page.setViewportSize({width:390,height:844});}
   await Promise.all([page.waitForResponse(r=>r.url().includes('/api/term-search')),page.getByRole('button',{name:'레퍼런스 검색',exact:true}).click()]);
   await page.goBack();await page.locator('.term-graph').waitFor();assert.equal(await readQuery(),combined);
    await page.locator('.term-graph-scene,.term-graph-list').first().waitFor();
    await page.waitForTimeout(120);
    const restoredSelectionCount=await page.locator('.term-graph-node[data-selected="true"],.term-graph-list input:checked').count();
    assert.equal(restoredSelectionCount,2);
   await page.goForward();if(mobile)await page.getByRole('button',{name:'레퍼런스',exact:true}).click();await page.getByText('검색 결과가 없습니다.',{exact:true}).first().waitFor();
   assert.equal(calls.length,1);
   if(mobile)await page.getByRole('button',{name:'대화',exact:true}).click();
   else assert.equal(await page.getByRole('textbox',{name:'캐릭터 설명'}).inputValue(),'내가 직접 작성한 초안');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.close();
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({querySync:true,multipleAndRapidSelection:true,deselection:true,list:true,backForward:true,draftPreserved:true,noAutomaticSearch:true,windowCentered:true,mobile:true,reducedMotion:true,graphGeometryUnchanged:true,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
