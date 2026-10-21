const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

function geometry(page) {
 return page.evaluate(()=>{
  const scene=document.querySelector('.term-graph-scene'),sr=scene.getBoundingClientRect();
  const nodes=[...document.querySelectorAll('.term-graph-node,.term-graph-category')].map(element=>{
   const rect=element.getBoundingClientRect(),label=element.querySelector('.term-graph-label');
   const anchor=rect;
   const style=getComputedStyle(element);
   return {id:element.dataset.nodeId,isDetail:element.dataset.detail==='true',x:rect.x-sr.x,y:rect.y-sr.y,width:rect.width,height:rect.height,
    cx:anchor.x-sr.x+anchor.width/2,cy:anchor.y-sr.y+anchor.height/2,
    world:[+element.dataset.worldX,+element.dataset.worldY,+element.dataset.worldZ],depth:+element.dataset.depth,
    labelVisible:Boolean(label)&&getComputedStyle(label).display!=='none',borderRadius:style.borderRadius,fontSize:parseFloat(style.fontSize)};
  });
  const labeled=nodes.filter(node=>node.labelVisible),overlaps=[];
  const severeOverlaps=[];
  for(let first=0;first<labeled.length;first++) for(let second=first+1;second<labeled.length;second++) {
   const a=labeled[first],b=labeled[second];
   const width=Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x);
   const height=Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y);
   if(width>1&&height>1) overlaps.push([a.id,b.id,Math.round(width*height)]);
   const distance=Math.hypot(a.cx-b.cx,a.cy-b.cy),combined=(a.width+b.width)/2;
   if(distance<combined*.4) severeOverlaps.push([a.id,b.id,Math.round(distance),Math.round(combined)]);
  }
  const obstacles=[...document.querySelectorAll('.history-logo,.recommended-query,.term-graph-view-toggle,.term-graph-tools,.term-graph-lower-overlay,.term-graph-relation-legend')]
   .filter(element=>getComputedStyle(element).display!=='none').map(element=>{const rect=element.getBoundingClientRect();
    return {name:element.className,x:rect.x-sr.x,y:rect.y-sr.y,width:rect.width,height:rect.height};});
  const overlayOverlaps=[];
  for(const node of labeled) for(const obstacle of obstacles) {
   const width=Math.min(node.x+node.width,obstacle.x+obstacle.width)-Math.max(node.x,obstacle.x);
   const height=Math.min(node.y+node.height,obstacle.y+obstacle.height)-Math.max(node.y,obstacle.y);
   if(width>1&&height>1) overlayOverlaps.push([node.id,obstacle.name,Math.round(width*height)]);
  }
  const byId=Object.fromEntries(nodes.map(node=>[node.id,node]));
  const expandContainmentErrors=[...document.querySelectorAll('.term-graph-expand')].map(element=>{
   const parent=byId[element.dataset.nodeId.replace(/:expand$/,'')],rect=element.getBoundingClientRect();
   return {id:element.dataset.nodeId,error:parent?Math.max(0,parent.x-(rect.x-sr.x),parent.y-(rect.y-sr.y),rect.right-sr.x-(parent.x+parent.width),rect.bottom-sr.y-(parent.y+parent.height)):Infinity};
  });
  const labelContainmentErrors=[...document.querySelectorAll('.term-graph-node .term-graph-label')]
   .filter(element=>getComputedStyle(element).display!=='none').map(element=>{
    const label=element.getBoundingClientRect(),node=element.closest('.term-graph-node').getBoundingClientRect();
    return Math.max(0,node.left-label.left,node.top-label.top,label.right-node.right,label.bottom-node.bottom);
   });
  const labelOcclusions=[...document.querySelectorAll('.term-graph-node .term-graph-label')].flatMap(label=>{
    const rect=label.getBoundingClientRect(),owner=label.closest('.term-graph-node'),samples=[
     [rect.left+rect.width/2,rect.top+rect.height/2],
     [rect.left+rect.width/2,rect.top+rect.height*.25],
     [rect.left+rect.width/2,rect.top+rect.height*.75],
     [rect.left+rect.width*.3,rect.top+rect.height/2],
     [rect.left+rect.width*.7,rect.top+rect.height/2],
    ];
    return samples.flatMap(([x,y])=>{
     if(x<0||y<0||x>=innerWidth||y>=innerHeight) return [];
     const top=document.elementFromPoint(x,y);
     return top&&owner.contains(top)?[]:[[owner.dataset.nodeId,top?.closest?.('.term-graph-node,.term-graph-expand')?.dataset?.nodeId||top?.className||null]];
    });
   });
  const expandOcclusions=[...document.querySelectorAll('.term-graph-expand')].flatMap(control=>{
    const rect=control.getBoundingClientRect(),x=rect.left+rect.width/2,y=rect.top+rect.height/2;
    if(x<0||y<0||x>=innerWidth||y>=innerHeight) return [];
    const top=document.elementFromPoint(x,y);
    return top&&control.contains(top)?[]:[[control.dataset.nodeId,top?.closest?.('.term-graph-node,.term-graph-expand')?.dataset?.nodeId||top?.className||null]];
   });
  const edgeMap=new Map();
  for(const element of document.querySelectorAll('.term-graph-scene line')) {
   const key=`${element.dataset.source}:${element.dataset.target}:${element.dataset.relation}`;
   const edge=edgeMap.get(key)||{source:element.dataset.source,target:element.dataset.target,relation:element.dataset.relation};
   if(element.dataset.endpoint==='source') Object.assign(edge,{x1:+element.getAttribute('x1')*sr.width/1000,y1:+element.getAttribute('y1')*sr.height/840});
   if(element.dataset.endpoint==='target') Object.assign(edge,{x2:+element.getAttribute('x2')*sr.width/1000,y2:+element.getAttribute('y2')*sr.height/840});
   edgeMap.set(key,edge);
  }
  const edges=[...edgeMap.values()];
  const endpointErrors=edges.flatMap(edge=>{
   const source=byId[edge.source],target=byId[edge.target];
   if(!source||!target) return [];
   return [{id:edge.source,error:Math.hypot(edge.x1-source.cx,edge.y1-source.cy),dx:edge.x1-source.cx,dy:edge.y1-source.cy},
    {id:edge.target,error:Math.hypot(edge.x2-target.cx,edge.y2-target.cy),dx:edge.x2-target.cx,dy:edge.y2-target.cy}];
  });
  const worldRadius=node=>Math.hypot(...node.world);
  const outwardViolations=edges.filter(edge=>edge.relation!=='category'&&byId[edge.target]?.isDetail&&
   worldRadius(byId[edge.target])<=worldRadius(byId[edge.source])+1).map(edge=>[edge.source,edge.target]);
  const worstEndpoint=endpointErrors.reduce((worst,item)=>item.error>worst.error?item:worst,{error:0});
  const worstExpand=expandContainmentErrors.reduce((worst,item)=>item.error>worst.error?item:worst,{error:0});
  const circularNodeErrors=nodes.filter(node=>!node.id.startsWith('category:')).map(node=>Math.max(
   Math.abs(node.width-node.height),node.borderRadius==='50%'?0:Math.abs(parseFloat(node.borderRadius)-node.width/2)));
  const offscreen=nodes.filter(node=>node.x<0||node.y<0||node.x+node.width>sr.width||node.y+node.height>sr.height)
   .map(node=>[node.id,Math.round(node.x),Math.round(node.y),Math.round(node.width),Math.round(node.height)]);
  const detailNodes=nodes.filter(node=>node.isDetail),logo=document.querySelector('.history-logo')?.getBoundingClientRect(),legend=document.querySelector('.term-graph-relation-legend')?.getBoundingClientRect();
  const logoLegendOverlap=logo&&legend?Math.max(0,Math.min(logo.right,legend.right)-Math.max(logo.left,legend.left))*Math.max(0,Math.min(logo.bottom,legend.bottom)-Math.max(logo.top,legend.top)):0;
  return {overlaps,severeOverlaps,overlayOverlaps,outwardViolations,maxEndpointError:worstEndpoint.error,worstEndpoint,
   maxExpandContainmentError:worstExpand.error,worstExpand,maxCircularNodeError:Math.max(0,...circularNodeErrors),
   dotCount:document.querySelectorAll('.term-graph-dot').length,maxLabelContainmentError:Math.max(...labelContainmentErrors),labelOcclusions,expandOcclusions,
   minDetailSize:Math.min(...detailNodes.map(node=>node.width)),minDetailFont:Math.min(...detailNodes.map(node=>node.fontSize)),offscreen,logoLegendOverlap,nodes,edges};
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

  const check=async (label,overlapLimit=Infinity,requireSeparatedCenters=false)=>{
   const result=await geometry(page);
   assert(result.overlaps.length<=overlapLimit,`${label}: visible-label overlaps grew to ${result.overlaps.length}: ${JSON.stringify(result.overlaps.slice(0,8))}`);
   if(requireSeparatedCenters) assert.deepEqual(result.severeOverlaps,[],`${label}: circular node centers stack: ${JSON.stringify(result.severeOverlaps)}`);
   assert(result.maxEndpointError<1,`${label}: edge endpoint misses its visible anchor: ${JSON.stringify(result.worstEndpoint)}`);
   assert(result.maxExpandContainmentError<1,`${label}: expand control escaped its node: ${JSON.stringify(result.worstExpand)}`);
   assert(result.maxCircularNodeError<1,`${label}: term nodes are not centered circles (${result.maxCircularNodeError}px)`);
   assert.equal(result.dotCount,0,`${label}: detached dot remains`);
   assert(result.maxLabelContainmentError<1,`${label}: label drifts outside its node by ${result.maxLabelContainmentError}px`);
    if(requireSeparatedCenters) {
     assert.deepEqual(result.labelOcclusions,[],`${label}: label center is hidden: ${JSON.stringify(result.labelOcclusions)}`);
     assert.deepEqual(result.expandOcclusions,[],`${label}: expand control is hidden: ${JSON.stringify(result.expandOcclusions)}`);
    }
   assert.deepEqual(result.outwardViolations,[],`${label}: branches returned inward: ${JSON.stringify(result.outwardViolations)}`);
   const incoming=new Map();
   for(const edge of result.edges) incoming.set(edge.target,(incoming.get(edge.target)||0)+1);
   assert.ok([...incoming.values()].every(count=>count<=1),`${label}: a child has multiple displayed parents: ${JSON.stringify([...incoming])}`);
   assert.equal(result.nodes.filter(node=>node.id==='pose_sitting_on_edge').length,1,`${label}: multi-parent node duplicates`);
   assert.deepEqual(result.edges.filter(edge=>edge.target==='pose_sitting_on_edge'&&edge.relation==='all')
    .map(edge=>edge.source),['pose_sitting'],`${label}: AND child visual owner changed`);
   assert.deepEqual(result.edges.filter(edge=>edge.target==='pose_action_two_hand_aiming'&&edge.relation==='any')
    .map(edge=>edge.source),['pose_sitting'],`${label}: OR child visual owner changed`);
   return result;
  };
  const initial=await check('desktop initial',Infinity,true);
  if(process.env.GRAPH_CAPTURE) await page.screenshot({path:process.env.GRAPH_CAPTURE,fullPage:true});
  assert(initial.overlaps.length<=25,`desktop initial: dense circular layout still has ${initial.overlaps.length} overlaps: ${JSON.stringify(initial.overlaps.slice(0,20))}`);
  assert(initial.minDetailSize>=68,`desktop initial: detail circles shrink below 68px (${initial.minDetailSize}px)`);
  assert(initial.minDetailFont>=14,`desktop initial: detail text shrinks below 14px (${initial.minDetailFont}px)`);
  assert.deepEqual(initial.offscreen,[],`desktop initial: nodes are clipped: ${JSON.stringify(initial.offscreen)}`);
  assert.equal(initial.logoLegendOverlap,0,'desktop initial: relation legend overlaps the logo');
  const scene=page.locator('.term-graph-scene');
  const fixedViewport=await page.locator('.term-graph').evaluate(element=>({
   scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,scrollTop:element.scrollTop,
   overlay:[...element.querySelectorAll('.term-graph-lower-overlay button,.term-graph-lower-overlay h2,.term-graph-lower-overlay p')]
    .filter(item=>getComputedStyle(item).display!=='none').map(item=>{const rect=item.getBoundingClientRect();return [item.textContent.trim(),rect.top,rect.bottom];})
  }));
  assert.equal(fixedViewport.scrollTop,0,'desktop graph starts vertically scrolled');
  assert(fixedViewport.scrollHeight<=fixedViewport.clientHeight+1,`desktop graph still needs vertical scrolling (${fixedViewport.scrollHeight}/${fixedViewport.clientHeight})`);
  assert(fixedViewport.overlay.every(([,top,bottom])=>top>=0&&bottom<=900),`lower graph controls are outside the viewport: ${JSON.stringify(fixedViewport.overlay)}`);
  const blank=await scene.evaluate(element=>{
   const rect=element.getBoundingClientRect();
   for(const y of [.18,.3,.42,.54,.66]) for(const x of [.12,.26,.4,.54,.68,.82]) {
    const px=rect.left+rect.width*x,py=rect.top+rect.height*y,target=document.elementFromPoint(px,py);
    if(target&&element.contains(target)&&!target.closest('.term-graph-node,.term-graph-expand')) return {x:px,y:py};
   }
   return {x:rect.left+20,y:rect.top+rect.height/2};
  });
  const zoomBefore=+(await scene.getAttribute('data-zoom'));
  await page.mouse.move(blank.x,blank.y);await page.mouse.wheel(0,-120);
  await page.waitForFunction(value=>+document.querySelector('.term-graph-scene').dataset.zoom>value,zoomBefore);
  const zoomAfter=+(await scene.getAttribute('data-zoom'));
  assert(zoomAfter>zoomBefore&&zoomAfter<=1.25,`graph wheel zoom is outside the safe range (${zoomBefore} -> ${zoomAfter})`);
  assert.equal(await page.locator('.term-graph').evaluate(element=>element.scrollTop),0,'graph wheel scrolled the central panel');
  const sidebar=page.locator('.history-sidebar-list');
  if(await sidebar.count()) {
   await sidebar.evaluate(element=>{for(let i=0;i<80;i++){const row=document.createElement('div');row.style.height='32px';row.textContent=`scroll-test-${i}`;element.append(row);}});
   const sideBox=await sidebar.boundingBox(),sideZoom=+(await scene.getAttribute('data-zoom'));
   if(sideBox) {
    await page.mouse.move(sideBox.x+sideBox.width/2,sideBox.y+sideBox.height/2);await page.mouse.wheel(0,240);
    await page.waitForFunction(()=>document.querySelector('.history-sidebar-list').scrollTop>0);
    assert.equal(+(await scene.getAttribute('data-zoom')),sideZoom,'sidebar wheel changed graph zoom');
   }
  }
  await scene.press('Home');
  const before=await geometry(page),beforeById=Object.fromEntries(before.nodes.map(node=>[node.id,node]));
  const bounds=await scene.boundingBox(),depthChanges=[];
  const dragStart=await scene.evaluate(element=>{
   const rect=element.getBoundingClientRect();
   for(const y of [.18,.3,.42,.54,.66]) for(const x of [.12,.26,.4,.54,.68,.82]) {
    const clientX=rect.left+rect.width*x,clientY=rect.top+rect.height*y,target=document.elementFromPoint(clientX,clientY);
    if(target&&element.contains(target)&&!target.closest('.term-graph-node,.term-graph-expand')) return {x:clientX,y:clientY};
   }
   return {x:rect.left+20,y:rect.top+rect.height/2};
  });
  await page.mouse.move(dragStart.x,dragStart.y);
  await page.mouse.down();
  for(let step=1;step<=6;step++) {
   await page.mouse.move(dragStart.x+bounds.width*step*.035,dragStart.y+bounds.height*step*.012);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const frameGeometry=await geometry(page);
   assert(frameGeometry.maxEndpointError<1,`drag frame ${step}: edge endpoint misses its node center by ${frameGeometry.maxEndpointError}px`);
   assert(frameGeometry.maxExpandContainmentError<1,`drag frame ${step}: expand control escaped its node by ${frameGeometry.maxExpandContainmentError}px`);
   assert(frameGeometry.maxLabelContainmentError<1,`drag frame ${step}: label drifts outside its node by ${frameGeometry.maxLabelContainmentError}px`);
   for(const node of frameGeometry.nodes) assert.deepEqual(node.world,beforeById[node.id].world,`drag frame ${step}: ${node.id} world anchor mutated`);
   depthChanges.push(Math.max(...frameGeometry.nodes.map(node=>Math.abs(node.depth-beforeById[node.id].depth))));
  }
  await page.mouse.up();
  assert(Math.max(...depthChanges)>1,'pointer drag did not change 3D depth');
  await scene.press('Home');
  const stableNode=page.locator('.term-graph-node[data-node-id="pose_contrapposto"]'),stableBox=await stableNode.boundingBox();
  const stableBefore=await geometry(page),stableView=await scene.evaluate(element=>[element.dataset.yaw,element.dataset.pitch,element.dataset.zoom]);
  await page.mouse.move(stableBox.x+stableBox.width/2,stableBox.y+stableBox.height/2);
  await page.mouse.down();await page.mouse.move(stableBox.x+stableBox.width/2+9,stableBox.y+stableBox.height/2+7);await page.mouse.up();
  const stableAfter=await geometry(page);
  assert.deepEqual(await scene.evaluate(element=>[element.dataset.yaw,element.dataset.pitch,element.dataset.zoom]),stableView,'pointer jitter on a node rotated the scene');
  assert.deepEqual(stableAfter.nodes.map(node=>[node.id,node.world,node.cx,node.cy]),stableBefore.nodes.map(node=>[node.id,node.world,node.cx,node.cy]),
   'selecting a node moved graph anchors');
  const selectedBeforeClick=await stableNode.getAttribute('data-selected');
  await stableNode.hover();await stableNode.click();
  assert.notEqual(await stableNode.getAttribute('data-selected'),selectedBeforeClick,'ordinary node click still toggles selection');
  const selectedGeometry=await geometry(page);
  assert.deepEqual(selectedGeometry.nodes.map(node=>[node.id,node.world,node.cx,node.cy]),stableBefore.nodes.map(node=>[node.id,node.world,node.cx,node.cy]),
   'hover or selection changed circular node anchors');
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
  const narrowClipped=await page.locator('.term-graph-node,.term-graph-category').evaluateAll(nodes=>nodes.flatMap(node=>{
   const rect=node.getBoundingClientRect();
   return rect.left<0||rect.top<0||rect.right>innerWidth||rect.bottom>innerHeight
    ?[[node.dataset.nodeId,Math.round(rect.left),Math.round(rect.top),Math.round(rect.width),Math.round(rect.height)]]:[];
  }));
  assert.deepEqual(narrowClipped,[],`narrow rotated and zoomed: nodes are clipped by the viewport: ${JSON.stringify(narrowClipped)}`);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({multipleBranches:true,initialVisibleLabelOverlaps:initial.overlaps.length,
   initialOverlapPairs:initial.overlaps,
   outwardBranches:true,singleDisplayedParent:true,circularNodes:true,integratedExpand:true,selectionStable:true,
   rigid3DWorld:true,independentYawPitch:true,depthChanges:true,endpointsMatchVisibleAnchors:true,andOr:true,noDuplicates:true,rotated:true,narrow:true}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
