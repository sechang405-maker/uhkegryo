const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

async function openPage(browser) {
 const page=await browser.newPage({viewport:{width:1474,height:933}});
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
  if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
  return route.abort();
 });
 await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
 await page.waitForLoadState('networkidle');
 return page;
}

async function edgeMismatches(page) {
 return page.locator('.term-graph-scene line').evaluateAll(lines=>lines.flatMap(line=>{
  const target=document.querySelector(`.term-graph-node[data-node-id="${line.dataset.target}"],.term-graph-category[data-node-id="${line.dataset.target}"]`);
  if(!target) return [];
  const stroke=getComputedStyle(line).stroke,border=getComputedStyle(target).borderTopColor;
  return stroke===border?[]:[{target:line.dataset.target,relation:line.dataset.relation,stroke,border}];
 }));
}

async function depthOverlaps(page) {
 return page.evaluate(()=>{
  return [...document.querySelectorAll('.term-graph-expand')].flatMap(control=>{
   const controlRect=control.getBoundingClientRect(),x=controlRect.left+controlRect.width/2,y=controlRect.top+controlRect.height/2;
   const ownerId=control.dataset.nodeId.replace(/:expand$/,''),owner=document.querySelector(`.term-graph-node[data-node-id="${ownerId}"]`);
   if(!owner) return [];
   const ownerDepth=+owner.dataset.depth;
   const groups=[...document.elementsFromPoint(x,y)].filter(element=>element.matches?.('.term-graph-node,.term-graph-expand'))
    .map(element=>{
     const id=element.dataset.nodeId.replace(/:expand$/,''),node=document.querySelector(`.term-graph-node[data-node-id="${id}"]`);
     return node?{id,depth:+node.dataset.depth}:null;
    }).filter(Boolean).filter((group,index,all)=>all.findIndex(candidate=>candidate.id===group.id)===index);
   const front=[...groups].sort((first,second)=>second.depth-first.depth)[0];
   if(!front||front.id===ownerId||front.depth<=ownerDepth+1) return [];
   return [{control:control.dataset.nodeId,front:front.id,top:groups[0]?.id||null,
    ownerDepth,frontDepth:front.depth,x,y}];
  });
 });
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const page=await openPage(browser);
  const categoryEdgeMismatches=await edgeMismatches(page);
  await page.locator('[data-node-id="pose_sitting:expand"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-node-id="pose_sitting_leaning_forward"]')?.dataset.motion==='idle');
  const relationshipEdgeMismatches=await edgeMismatches(page);

  let overlaps=[];
  for(let step=0;step<20;step++) {
   overlaps.push(...await depthOverlaps(page));
   await page.locator('.term-graph-scene').press(step%5===4?'ArrowDown':'ArrowRight');
  }
  assert(overlaps.length>0,'rotation did not produce a real front-node/rear-control overlap');
  const violations=overlaps.filter(overlap=>overlap.top!==overlap.front);
  await page.locator('.term-graph-tools summary').click();
  await page.locator('.term-graph-controls button').last().click();
  let sample;
  for(let step=0;step<20&&!sample;step++) {
   sample=(await depthOverlaps(page))[0];
   if(!sample) await page.locator('.term-graph-scene').press(step%5===4?'ArrowDown':'ArrowRight');
  }
  assert(sample,'camera orbit must retain the reported overlap regression fixture');
  const front=page.locator(`[data-node-id="${sample.front}"]`);
  await front.hover();
  await front.focus();
  await front.click();
  const styledViolations=(await depthOverlaps(page)).filter(overlap=>overlap.top!==overlap.front);
  assert.deepEqual({categoryEdgeMismatches,relationshipEdgeMismatches,violations,styledViolations},
   {categoryEdgeMismatches:[],relationshipEdgeMismatches:[],violations:[],styledViolations:[]},
   'edge category colors and camera-depth stacking must remain consistent');
  if(process.env.SCREENSHOT_PATH) await page.screenshot({path:process.env.SCREENSHOT_PATH,fullPage:true});
  console.log('graph edge color and depth stacking checks passed');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
