const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

async function settle(page,id) {
 await page.waitForFunction(nodeId=>document.querySelector(`[data-node-id="${nodeId}"]`)?.dataset.motion==='idle',id);
}

async function openPage(browser,options={}) {
 const page=await browser.newPage({viewport:{width:1474,height:933},...options});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>{
  window.__graphMotionListeners={visibility:0,media:0};
  const add=Document.prototype.addEventListener,remove=Document.prototype.removeEventListener;
  Document.prototype.addEventListener=function(type,...args){if(type==='visibilitychange') window.__graphMotionListeners.visibility++;return add.call(this,type,...args);};
  Document.prototype.removeEventListener=function(type,...args){if(type==='visibilitychange') window.__graphMotionListeners.visibility--;return remove.call(this,type,...args);};
  const nativeMatch=window.matchMedia.bind(window),patched=new WeakSet();
  window.matchMedia=query=>{
   const media=nativeMatch(query);
   if(query==='(prefers-reduced-motion: reduce)'&&!patched.has(media)) {
    patched.add(media);const mediaAdd=media.addEventListener.bind(media),mediaRemove=media.removeEventListener.bind(media);
    media.addEventListener=(type,...args)=>{if(type==='change') window.__graphMotionListeners.media++;return mediaAdd(type,...args);};
    media.removeEventListener=(type,...args)=>{if(type==='change') window.__graphMotionListeners.media--;return mediaRemove(type,...args);};
   }
   return media;
  };
 });
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

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const {page,errors}=await openPage(browser);
  const scene=page.locator('.term-graph-scene'),expand=page.locator('[data-node-id="pose_sitting:expand"]');
  const stable=page.locator('[data-node-id="pose_contrapposto"]');
  const stableBefore=await stable.evaluate(node=>[node.dataset.worldX,node.dataset.worldY,node.dataset.worldZ,node.dataset.layoutX,node.dataset.layoutY]);
  const ambient=await page.evaluate(()=>document.getAnimations().filter(animation=>animation.animationName==='term-graph-idle-glow')
   .map(animation=>({duration:animation.effect.getTiming().duration,iterations:animation.effect.getTiming().iterations})));
  assert(ambient.some(animation=>animation.duration===4800&&animation.iterations===1),'idle glow must be a bounded one-shot animation');

  await expand.click();
  await page.locator('[data-node-id="pose_sitting_leaning_forward"]').waitFor();
  const enter=[],anchorErrors=[];
  for(let frame=0;frame<10;frame++) {
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
   const sample=await page.evaluate(()=>{
    const node=document.querySelector('[data-node-id="pose_sitting_leaning_forward"]');
    const line=document.querySelector('line[data-target="pose_sitting_leaning_forward"]');
    if(!node||!line) return null;
    return {amount:+node.dataset.motionAmount,disabled:node.disabled,
     error:Math.hypot(+line.getAttribute('x2')-(+node.dataset.layoutX),+line.getAttribute('y2')-(+node.dataset.layoutY))};
   });
   if(sample){enter.push(sample.amount);anchorErrors.push(sample.error);if(sample.amount<1) assert.equal(sample.disabled,true);}
  }
  assert(enter.some(value=>value>0&&value<1),'enter motion did not expose intermediate frames');
  assert(enter.every((value,index)=>index===0||value>=enter[index-1]),`enter motion reversed: ${enter}`);
  assert(Math.max(...anchorErrors)<.001,`edge and node did not share the interpolated anchor: ${Math.max(...anchorErrors)}`);
  assert.deepEqual(await stable.evaluate(node=>[node.dataset.worldX,node.dataset.worldY,node.dataset.worldZ,node.dataset.layoutX,node.dataset.layoutY]),stableBefore,
   'an unrelated branch moved during expansion');
  await settle(page,'pose_sitting_leaning_forward');
  assert.equal(await page.locator('[data-node-id="pose_sitting_leaning_forward"]').isEnabled(),true);

  await expand.click();
  const exit=[];
  for(let frame=0;frame<6;frame++) {
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
   const node=page.locator('[data-node-id="pose_sitting_leaning_forward"]');
   if(!await node.count()) break;
   exit.push(+(await node.getAttribute('data-motion-amount')));
   assert.equal(await node.getAttribute('aria-hidden'),'true');
   assert.equal(await node.isDisabled(),true);
  }
  assert(exit.some(value=>value>0&&value<1),'exit motion did not expose intermediate frames');
  assert(exit.every((value,index)=>index===0||value<=exit[index-1]),`exit motion restarted: ${exit}`);
  await page.waitForFunction(()=>!document.querySelector('[data-node-id="pose_sitting_leaning_forward"]'));

  // Reverse twice while the same child is in flight. It must stay unique and
  // settle to the last requested state without a stale completion callback.
  await expand.click();await page.waitForTimeout(45);
  await expand.click();await page.waitForTimeout(35);
  await expand.click();
  await settle(page,'pose_sitting_leaning_forward');
  assert.equal(await page.locator('[data-node-id="pose_sitting_leaning_forward"]').count(),1);
  assert.equal(await page.locator('line[data-target="pose_sitting_leaning_forward"]').count(),1);

  const viewBefore=await scene.evaluate(node=>[node.dataset.yaw,node.dataset.pitch,node.dataset.zoom]);
  await expand.click();await page.waitForFunction(()=>!document.querySelector('[data-node-id="pose_sitting_leaning_forward"]'));
  await expand.click();
  const box=await scene.boundingBox();
  await page.mouse.move(box.x+24,box.y+box.height*.48);await page.mouse.down();
  await page.mouse.move(box.x+40,box.y+box.height*.50,{steps:2});await page.mouse.wheel(0,-80);
  const heldZoom=await scene.getAttribute('data-zoom');
  await page.mouse.move(box.x+58,box.y+box.height*.52,{steps:3});
  assert.equal(await scene.getAttribute('data-zoom'),heldZoom,'pointer move rolled back wheel zoom while drag stayed held');
  await page.mouse.up();
  await settle(page,'pose_sitting_leaning_forward');
  const viewAfter=await scene.evaluate(node=>[node.dataset.yaw,node.dataset.pitch,node.dataset.zoom]);
  assert.notDeepEqual(viewAfter,viewBefore,'wheel and drag input stopped responding during motion');
  const endpointError=await page.evaluate(()=>Math.max(0,...[...document.querySelectorAll('.term-graph-scene line')].map(line=>{
   const target=document.querySelector(`.term-graph-node[data-node-id="${line.dataset.target}"],.term-graph-category[data-node-id="${line.dataset.target}"]`);
   return target?Math.hypot(+line.getAttribute('x2')-(+target.dataset.layoutX),+line.getAttribute('y2')-(+target.dataset.layoutY)):0;
  })));
  assert(endpointError<.001,`final edge anchor error ${endpointError}`);

  // A shared child keeps one edge while ownership changes, and glides from its
  // prior fixed world point instead of snapping to the next parent's layout.
  const standingExpand=page.locator('[data-node-id="pose_standing:expand"]');
  await standingExpand.click();
  await page.waitForFunction(()=>document.querySelector('.term-graph-scene')?.dataset.animating==='false');
  assert.equal(await page.locator('line[data-target="pose_action_two_hand_aiming"][data-source="pose_sitting"]').count(),1);
  await expand.click();
  const shared=page.locator('[data-node-id="pose_action_two_hand_aiming"]');
  assert.equal(await shared.getAttribute('data-motion'),'enter');
  assert.equal(await page.locator('line[data-target="pose_action_two_hand_aiming"][data-source="pose_standing"]').count(),1);
  assert.equal(await page.locator('line[data-target="pose_action_two_hand_aiming"]').count(),1);
  for(let frame=0;frame<4;frame++) {
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
   const error=await page.evaluate(()=>{
    const node=document.querySelector('[data-node-id="pose_action_two_hand_aiming"]'),line=document.querySelector('line[data-target="pose_action_two_hand_aiming"]');
    return Math.hypot(+line.getAttribute('x2')-(+node.dataset.layoutX),+line.getAttribute('y2')-(+node.dataset.layoutY));
   });
   assert(error<.001,`owner-transfer edge lost its node anchor by ${error}`);
  }
  await settle(page,'pose_action_two_hand_aiming');

  const listenersBeforeList=await page.evaluate(()=>({...window.__graphMotionListeners}));
  await page.locator('.term-graph-view-toggle button').click();
  await page.locator('.term-graph-list').waitFor();
  const listenersInList=await page.evaluate(()=>({...window.__graphMotionListeners}));
  assert.equal(listenersInList.visibility,listenersBeforeList.visibility-1,'list mode retained the graph visibility listener');
  assert.equal(listenersInList.media,listenersBeforeList.media-1,'list mode retained the graph reduced-motion listener');
  await page.locator('.term-graph-view-toggle button').click();
  await scene.waitFor();
  const listenersAfterList=await page.evaluate(()=>({...window.__graphMotionListeners}));
  assert.deepEqual(listenersAfterList,listenersBeforeList,'3D return did not restore exactly one listener pair');
  assert.equal(await page.locator('[data-motion="enter"],[data-motion="exit"]').count(),0,'list round trip left stale presence nodes');
  assert.deepEqual(errors,[]);
  await page.close();

  const reduced=await openPage(browser,{reducedMotion:'reduce'}),reducedPage=reduced.page;
  await reducedPage.locator('[data-node-id="pose_sitting:expand"]').click();
  const reducedChild=reducedPage.locator('[data-node-id="pose_sitting_leaning_forward"]');
  await reducedChild.waitFor();
  assert.equal(await reducedChild.getAttribute('data-motion'),'idle');
  assert.equal(await reducedPage.evaluate(()=>document.getAnimations().filter(animation=>animation.animationName==='term-graph-idle-glow').length),0);
  assert.deepEqual(reduced.errors,[]);await reducedPage.close();

  const mobile=await openPage(browser,{viewport:{width:390,height:844},isMobile:true,hasTouch:true}),mobilePage=mobile.page;
  await mobilePage.locator('.term-graph-list').waitFor();
  await mobilePage.locator('.term-graph-view-toggle button').click();
  assert.equal(await mobilePage.evaluate(()=>document.getAnimations().filter(animation=>animation.animationName==='term-graph-idle-glow').length),0,'mobile ambient motion must stay off');
  await mobilePage.locator('[data-node-id="pose_sitting:expand"]').click({force:true});
  await settle(mobilePage,'pose_sitting_leaning_forward');
  assert.equal(await mobilePage.locator('[data-node-id="pose_sitting_leaning_forward"]').count(),1);
  assert.deepEqual(mobile.errors,[]);await mobilePage.close();

  console.log(JSON.stringify({idleBounded:true,enterExit:true,rapidReversal:true,sharedOwnerGlide:true,sharedAnchors:true,unrelatedStable:true,
   wheelAndDragDuringMotion:true,listCleanup:true,listenerCleanup:true,reducedMotion:true,mobile:true}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
