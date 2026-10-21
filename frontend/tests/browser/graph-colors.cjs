const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

async function openPage(browser,viewport) {
 const page=await browser.newPage({viewport});
 const errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
  if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
  return route.abort();
 });
 await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
 await page.waitForLoadState('networkidle');
 return {page,errors};
}

async function border(locator) {
 return locator.evaluate(node=>getComputedStyle(node).borderTopColor);
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  for(const viewport of [{width:1474,height:933},{width:1120,height:800}]) {
   const {page,errors}=await openPage(browser,viewport);
   const roles=['body','pose','composition','perspective'];
   const categoryColors={};
   for(const role of roles) {
    const category=page.locator(`.term-graph-category[data-category="${role}"]`);
    categoryColors[role]=await border(category);
    assert.equal(await category.getAttribute('data-category'),role);
    const term=page.locator(`.term-graph-node[data-category="${role}"]`).first();
    assert.equal(await border(term),categoryColors[role],`${role} term does not inherit its category border`);
   }
   assert.equal(new Set(Object.values(categoryColors)).size,roles.length,'category borders are not visually distinct');

   const pose=page.locator('.term-graph-node[data-node-id="pose_sitting"]');
   const poseColor=categoryColors.pose;
   assert.equal(await border(pose),poseColor);
   const normalWidth=await pose.evaluate(node=>parseFloat(getComputedStyle(node).borderTopWidth));
   await pose.hover();
   assert.equal(await border(pose),poseColor,'hover replaced the category border');
   await pose.click();
   assert.equal(await pose.getAttribute('data-selected'),'true');
   assert.equal(await border(pose),poseColor,'selection replaced the category border');
   assert((await pose.evaluate(node=>parseFloat(getComputedStyle(node).borderTopWidth)))>normalWidth,'selection lacks a non-color border cue');
   assert.notEqual(await pose.evaluate(node=>getComputedStyle(node).boxShadow),'none','selection lacks a non-color glow cue');

   const expand=page.locator('[data-node-id="pose_sitting:expand"]');
   assert.equal(await border(expand),poseColor,'expand control does not inherit the category border');
   await expand.click();
   const child=page.locator('.term-graph-node[data-node-id="pose_sitting_leaning_forward"]');
   await child.waitFor();
   await page.waitForFunction(()=>document.querySelector('[data-node-id="pose_sitting_leaning_forward"]')?.dataset.motion==='idle');
   assert.equal(await child.getAttribute('data-category'),'pose');
   const childColor=await border(child);
   assert.notEqual(childColor,poseColor,'expanded child is not visually distinct from its parent');
   assert.equal(await border(expand),poseColor,'parent changed to the child hierarchy tone');
   const childEdge=page.locator('.term-graph-edge-layer line[data-target="pose_sitting_leaning_forward"]').first();
   assert.equal(await childEdge.evaluate(node=>getComputedStyle(node).stroke),childColor,'child edge and node hierarchy colors diverged');

   const before=await child.evaluate(node=>({border:getComputedStyle(node).borderTopColor,world:[node.dataset.worldX,node.dataset.worldY,node.dataset.worldZ]}));
   await page.locator('.term-graph-scene').press('ArrowRight');
   const after=await child.evaluate(node=>({border:getComputedStyle(node).borderTopColor,world:[node.dataset.worldX,node.dataset.worldY,node.dataset.worldZ]}));
   assert.equal(after.border,before.border,'rotation changed the child hierarchy border');
   assert.deepEqual(after.world,before.world,'rotation changed fixed world coordinates');
   assert.equal(await page.locator('.term-graph-node').evaluateAll(nodes=>Math.min(...nodes.map(node=>parseFloat(getComputedStyle(node).fontSize)))),14);
   if(process.env.SCREENSHOT_PATH&&viewport.width===1474) await page.screenshot({path:process.env.SCREENSHOT_PATH,fullPage:true});
   assert.deepEqual(errors,[]);
   await page.close();
  }
  console.log('graph category color browser checks passed');
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
