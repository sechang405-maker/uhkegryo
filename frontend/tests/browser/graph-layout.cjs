const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

function geometry(page) {
 return page.evaluate(()=>{
  const scene=document.querySelector('.term-graph-scene'),sr=scene.getBoundingClientRect();
  const nodes=[...document.querySelectorAll('.term-graph-node,.term-graph-category')].map(element=>{
   const rect=element.getBoundingClientRect(),label=element.querySelector('.term-graph-label'),dot=element.querySelector('.term-graph-dot');
   const anchor=(dot||element).getBoundingClientRect();
   return {id:element.dataset.nodeId,isDetail:element.dataset.detail==='true',x:rect.x-sr.x,y:rect.y-sr.y,width:rect.width,height:rect.height,
    cx:anchor.x-sr.x+anchor.width/2,cy:anchor.y-sr.y+anchor.height/2,
    world:[element.dataset.worldX,element.dataset.worldY,element.dataset.worldZ],depth:+element.dataset.depth,
    labelVisible:Boolean(label)&&getComputedStyle(label).display!=='none'};
  });
  const labeled=nodes.filter(node=>node.labelVisible),overlaps=[];
  for(let first=0;first<labeled.length;first++) for(let second=first+1;second<labeled.length;second++) {
   const a=labeled[first],b=labeled[second];
   const width=Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x);
   const height=Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y);
   if(width>1&&height>1) overlaps.push([a.id,b.id,Math.round(width*height)]);
  }
  const obstacles=[...document.querySelectorAll('.recommended-query,.term-graph-view-toggle,.term-graph-tools,.term-graph-lower-overlay')]
   .filter(element=>getComputedStyle(element).display!=='none').map(element=>{const rect=element.getBoundingClientRect();
    return {name:element.className,x:rect.x-sr.x,y:rect.y-sr.y,width:rect.width,height:rect.height};});
  const overlayOverlaps=[];
  for(const node of labeled) for(const obstacle of obstacles) {
   const width=Math.min(node.x+node.width,obstacle.x+obstacle.width)-Math.max(node.x,obstacle.x);
   const height=Math.min(node.y+node.height,obstacle.y+obstacle.height)-Math.max(node.y,obstacle.y);
   if(width>1&&height>1) overlayOverlaps.push([node.id,obstacle.name,Math.round(width*height)]);
  }
  const byId=Object.fromEntries(nodes.map(node=>[node.id,node]));
  const expandAnchorErrors=[...document.querySelectorAll('.term-graph-expand')].map(element=>{
   const parent=byId[element.dataset.nodeId.replace(/:expand$/,'')],rect=element.getBoundingClientRect();
   return parent?Math.abs(Math.hypot(rect.x-sr.x+rect.width/2-parent.cx,rect.y-sr.y+rect.height/2-parent.cy)-42):Infinity;
  });
  const labelContainmentErrors=[...document.querySelectorAll('.term-graph-node .term-graph-label')]
   .filter(element=>getComputedStyle(element).display!=='none').map(element=>{
    const label=element.getBoundingClientRect(),node=element.closest('.term-graph-node').getBoundingClientRect();
    return Math.max(0,node.left-label.left,node.top-label.top,label.right-node.right,label.bottom-node.bottom);
   });
  const edges=[...document.querySelectorAll('.term-graph-scene line')].map(element=>({
   source:element.dataset.source,target:element.dataset.target,relation:element.dataset.relation,
   x1:+element.getAttribute('x1')*sr.width/1000,y1:+element.getAttribute('y1')*sr.height/700,
   x2:+element.getAttribute('x2')*sr.width/1000,y2:+element.getAttribute('y2')*sr.height/700,
  }));
  const endpointErrors=edges.flatMap(edge=>{
   const source=byId[edge.source],target=byId[edge.target];
   if(!source||!target) return [];
   return [{id:edge.source,error:Math.hypot(edge.x1-source.cx,edge.y1-source.cy),dx:edge.x1-source.cx,dy:edge.y1-source.cy},
    {id:edge.target,error:Math.hypot(edge.x2-target.cx,edge.y2-target.cy),dx:edge.x2-target.cx,dy:edge.y2-target.cy}];
  });
  const worstEndpoint=endpointErrors.reduce((worst,item)=>item.error>worst.error?item:worst,{error:0});
  return {overlaps,overlayOverlaps,maxEndpointError:worstEndpoint.error,worstEndpoint,
   maxExpandAnchorError:Math.max(...expandAnchorErrors),maxLabelContainmentError:Math.max(...labelContainmentErrors),nodes,edges};
 });
}

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
   if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
   return route.abort();
  });
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
  await page.waitForLoadState('networkidle');
  for(const id of ['pose_sitting','pose_standing','pose_contrapposto'])
   await page.locator(`[data-node-id="${id}:expand"]`).click({force:true});

  const check=async (label,overlapLimit=Infinity)=>{
   const result=await geometry(page);
   assert(result.overlaps.length<=overlapLimit,`${label}: visible-label overlaps grew to ${result.overlaps.length}: ${JSON.stringify(result.overlaps.slice(0,8))}`);
   assert(result.maxEndpointError<1,`${label}: edge endpoint misses its visible anchor: ${JSON.stringify(result.worstEndpoint)}`);
   assert(result.maxExpandAnchorError<1,`${label}: expand control drifts from its node by ${result.maxExpandAnchorError}px`);
   assert(result.maxLabelContainmentError<1,`${label}: label drifts outside its node by ${result.maxLabelContainmentError}px`);
   assert.equal(result.nodes.filter(node=>node.id==='pose_sitting_on_edge').length,1,`${label}: multi-parent node duplicates`);
   assert.deepEqual(result.edges.filter(edge=>edge.target==='pose_sitting_on_edge'&&edge.relation==='all')
    .map(edge=>edge.source).sort(),['pose_sitting','pose_support_chair'],`${label}: AND parents changed`);
   assert.deepEqual(result.edges.filter(edge=>edge.target==='pose_action_two_hand_aiming'&&edge.relation==='any')
    .map(edge=>edge.source).sort(),['pose_sitting','pose_standing'],`${label}: OR parents changed`);
   return result;
  };
  const initial=await check('desktop initial',0);
  const scene=page.locator('.term-graph-scene');
  const before=await geometry(page),beforeById=Object.fromEntries(before.nodes.map(node=>[node.id,node]));
  const bounds=await scene.boundingBox(),depthChanges=[];
  await page.mouse.move(bounds.x+bounds.width*.5,bounds.y+bounds.height*.2);
  await page.mouse.down();
  for(let step=1;step<=6;step++) {
   await page.mouse.move(bounds.x+bounds.width*(.5+step*.035),bounds.y+bounds.height*(.2+step*.012));
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const frameGeometry=await geometry(page);
   assert(frameGeometry.maxEndpointError<1,`drag frame ${step}: edge endpoint misses its node center by ${frameGeometry.maxEndpointError}px`);
   assert(frameGeometry.maxExpandAnchorError<1,`drag frame ${step}: expand control drifts from its node by ${frameGeometry.maxExpandAnchorError}px`);
   assert(frameGeometry.maxLabelContainmentError<1,`drag frame ${step}: label drifts outside its node by ${frameGeometry.maxLabelContainmentError}px`);
   for(const node of frameGeometry.nodes) assert.deepEqual(node.world,beforeById[node.id].world,`drag frame ${step}: ${node.id} world anchor mutated`);
   depthChanges.push(Math.max(...frameGeometry.nodes.map(node=>Math.abs(node.depth-beforeById[node.id].depth))));
  }
  await page.mouse.up();
  assert(Math.max(...depthChanges)>1,'pointer drag did not change 3D depth');
  await scene.press('Home');
  const home=await geometry(page),homeById=Object.fromEntries(home.nodes.map(node=>[node.id,node]));
  await scene.press('ArrowRight');
  const yaw=await geometry(page),yawById=Object.fromEntries(yaw.nodes.map(node=>[node.id,node]));
  await scene.press('ArrowLeft');
  const returned=await geometry(page),returnedById=Object.fromEntries(returned.nodes.map(node=>[node.id,node]));
  const returnError=Math.max(...Object.keys(homeById).map(id=>Math.hypot(returnedById[id].cx-homeById[id].cx,returnedById[id].cy-homeById[id].cy)));
  assert(returnError<1,`rotation back shifts layout ${returnError}px`);
  await scene.press('ArrowDown');
  const pitch=await geometry(page),pitchById=Object.fromEntries(pitch.nodes.map(node=>[node.id,node]));
  assert(Object.keys(homeById).some(id=>Math.abs(yawById[id].depth-homeById[id].depth)>1),'yaw does not change depth');
  assert(Object.keys(homeById).some(id=>Math.abs(pitchById[id].depth-homeById[id].depth)>1),'pitch does not change depth');
  assert(Object.keys(homeById).some(id=>Math.hypot(yawById[id].cx-pitchById[id].cx,yawById[id].cy-pitchById[id].cy)>5),'yaw and pitch are not independent');
  await scene.press('Home');
  for(let count=0;count<3;count++) await scene.press('ArrowRight');
  await scene.press('+');
  await check('desktop rotated and zoomed');
  await page.setViewportSize({width:390,height:844});
  await check('narrow rotated and zoomed');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({multipleBranches:true,initialVisibleLabelOverlaps:initial.overlaps.length,
   initialOverlapPairs:initial.overlaps,
   rigid3DWorld:true,independentYawPitch:true,depthChanges:true,endpointsMatchVisibleAnchors:true,andOr:true,noDuplicates:true,rotated:true,narrow:true}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
