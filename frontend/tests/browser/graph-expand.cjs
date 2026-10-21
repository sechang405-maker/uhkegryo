const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 const errors=[];
 try {
  for(const mobile of [false,true]) {
   const page=await browser.newPage({viewport:mobile?{width:390,height:844}:{width:1440,height:900},isMobile:mobile,hasTouch:mobile});
   const searches=[];
   page.on('pageerror',error=>errors.push(error.message));
   await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
    if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
    if(path==='/api/term-search') {
     const body=route.request().postDataJSON();searches.push(body);
     return route.fulfill({json:{term_id:body.term_id,role:'pose',label_ko:'앉아서 앞으로 숙이기',recommended_search_query:'sitting leaning forward drawing',pins:[],reason_codes:['PIN_RESULTS_EMPTY']}});
    }
    return route.abort();
   });
   await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
   await page.waitForLoadState('networkidle');
   if(mobile) {
    await page.locator('.term-graph-list').waitFor();
    await page.locator('.term-graph-view-toggle button').click();
   }
   const scene=page.locator('.term-graph-scene');
   const initialView=await scene.evaluate(element=>[element.dataset.yaw,element.dataset.pitch,element.dataset.zoom]);
   const expand=page.locator('[data-node-id="pose_sitting:expand"]');
   const box=await expand.boundingBox();assert(box.width>=24&&box.height>=24,'integrated expand control remains touchable');
   await expand.click({force:true});
   await page.locator('.term-graph-node[data-node-id="pose_sitting_leaning_forward"]').waitFor();
   await page.waitForFunction(()=>document.querySelector('[data-node-id="pose_sitting_leaning_forward"]')?.dataset.motion==='idle');
   assert.equal(await page.locator('.term-graph-node[data-node-id="pose_sitting_on_edge"]').count(),1);
   assert.equal(await page.locator('line[data-source="pose_sitting"][data-target="pose_sitting_on_edge"][data-relation="all"][data-endpoint="target"]').count(),1);
   assert.equal(await page.locator('line[data-source="pose_support_chair"][data-target="pose_sitting_on_edge"]').count(),0);
   assert.equal(await page.locator('line[data-source="pose_sitting"][data-target="pose_action_two_hand_aiming"][data-relation="any"][data-endpoint="target"]').count(),1);
   assert.equal(await page.locator('line[data-source="pose_standing"][data-target="pose_action_two_hand_aiming"]').count(),0);
   assert.deepEqual(await scene.evaluate(element=>[element.dataset.yaw,element.dataset.pitch,element.dataset.zoom]),initialView,'expand must not rotate or zoom the graph');
   assert.equal(await page.locator('.term-graph-node[data-selected="true"]').count(),0,'expand must not select its parent');

   const detail=page.locator('.term-graph-node[data-node-id="pose_sitting_leaning_forward"]');
   await detail.click({force:true});
   assert.equal(await detail.getAttribute('data-selected'),'true',`${mobile?'mobile':'desktop'} detail remains selectable after expansion`);
   await expand.click({force:true});
   await page.waitForFunction(()=>!document.querySelector('.term-graph-node[data-node-id="pose_sitting_leaning_forward"]'));
   assert.equal(await detail.count(),0,'collapse hides descendants');
   assert.match(await page.locator('[aria-label="추천 검색어"]').innerText(),/leaning forward/,'collapse preserves selected query');
   await expand.click({force:true});
   await page.waitForFunction(()=>document.querySelector('[data-node-id="pose_sitting_leaning_forward"]')?.dataset.motion==='idle');
   assert.equal(await page.locator('.term-graph-node[data-node-id="pose_sitting_leaning_forward"][data-selected="true"]').count(),1,'re-expansion preserves selection');
   assert.equal(await page.locator('.term-graph-node[data-node-id="pose_sitting_on_edge"]').count(),1,'repeated expansion never duplicates nodes');
   const world=()=>page.locator('.term-graph-node').evaluateAll(nodes=>Object.fromEntries(nodes.map(node=>[node.dataset.nodeId,
    [node.dataset.worldX,node.dataset.worldY,node.dataset.worldZ]])));
   const beforeStanding=await world();
   const standingExpand=page.locator('[data-node-id="pose_standing:expand"]');
   await standingExpand.click({force:true});
   const afterStanding=await world();
   for(const [id,coordinates] of Object.entries(beforeStanding)) assert.deepEqual(afterStanding[id],coordinates,`${id} moved when an unrelated branch expanded`);
   assert.equal(await page.locator('line[data-source="pose_sitting"][data-target="pose_action_two_hand_aiming"][data-endpoint="target"]').count(),1,
    'later expansion does not attach another parent to an existing child');
   assert.equal(await page.locator('line[data-source="pose_standing"][data-target="pose_action_two_hand_aiming"]').count(),0);
   await expand.click({force:true});
   assert.equal(await page.locator('.term-graph-node[data-node-id="pose_action_two_hand_aiming"]').count(),1,'shared child stays visible through its other parent');
   assert.equal(await page.locator('line[data-source="pose_standing"][data-target="pose_action_two_hand_aiming"][data-endpoint="target"]').count(),1,
    'remaining expanded parent takes visual ownership');
   await expand.click({force:true});
   assert.equal(await page.locator('line[data-source="pose_standing"][data-target="pose_action_two_hand_aiming"][data-endpoint="target"]').count(),1,
    're-expanding an older parent does not steal visual ownership');
   const incomingCounts=await page.locator('.term-graph-scene line[data-endpoint="target"]').evaluateAll(lines=>{
    const counts={};for(const line of lines) counts[line.dataset.target]=(counts[line.dataset.target]||0)+1;return counts;
   });
   assert.ok(Object.values(incomingCounts).every(count=>count<=1),'every displayed term has at most one parent edge');
   await Promise.all([
    page.waitForResponse(response=>response.url().includes('/api/term-search')),
    page.getByRole('button',{name:'레퍼런스 검색',exact:true}).click(),
   ]);
   assert.deepEqual(searches,[{term_id:'pose_sitting_leaning_forward'}]);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await page.close();
  }
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({desktop:true,mobile:true,semanticAndOrPreserved:true,singleDisplayedParent:true,stableSharedOwnership:true,noDuplicate:true,selectionSurvivesCollapse:true,termSearch:true,noRotationCollision:true,touchTarget:true}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
