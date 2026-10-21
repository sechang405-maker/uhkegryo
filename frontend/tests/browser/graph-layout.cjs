const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

function geometry(page) {
 return page.evaluate(()=>{
  const scene=document.querySelector('.term-graph-scene'),sr=scene.getBoundingClientRect();
  const nodes=[...document.querySelectorAll('.term-graph-node,.term-graph-category')].map(element=>{
   const rect=element.getBoundingClientRect(),label=element.querySelector('.term-graph-label');
   return {id:element.dataset.nodeId,isDetail:element.dataset.detail==='true',x:rect.x-sr.x,y:rect.y-sr.y,width:rect.width,height:rect.height,
    cx:rect.x-sr.x+rect.width/2,cy:rect.y-sr.y+rect.height/2,
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
   return [Math.hypot(edge.x1-source.cx,edge.y1-source.cy),Math.hypot(edge.x2-target.cx,edge.y2-target.cy)];
  });
  return {overlaps,overlayOverlaps,maxEndpointError:Math.max(...endpointErrors),
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
   assert(result.maxEndpointError<1,`${label}: edge endpoint misses its node center by ${result.maxEndpointError}px`);
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
  const centers=()=>page.locator('.term-graph-node').evaluateAll(elements=>Object.fromEntries(elements.map(element=>{
   const rect=element.getBoundingClientRect();return[element.dataset.nodeId,[rect.x+rect.width/2,rect.y+rect.height/2]];
  })));
  const before=await centers();
  const pairDistances=points=>{
   const ids=Object.keys(points),distances={};
   for(let first=0;first<ids.length;first++) for(let second=first+1;second<ids.length;second++) {
    const a=ids[first],b=ids[second];
    distances[`${a}:${b}`]=Math.hypot(points[a][0]-points[b][0],points[a][1]-points[b][1]);
   }
   return distances;
  };
  const initialDistances=pairDistances(before),bounds=await scene.boundingBox(),dragErrors=[];
  await page.mouse.move(bounds.x+bounds.width*.5,bounds.y+bounds.height*.2);
  await page.mouse.down();
  for(let step=1;step<=6;step++) {
   await page.mouse.move(bounds.x+bounds.width*(.5+step*.035),bounds.y+bounds.height*(.2+step*.012));
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const frame=await centers(),distances=pairDistances(frame);
   dragErrors.push(Math.max(...Object.keys(initialDistances).map(key=>Math.abs(distances[key]-initialDistances[key]))));
   const frameGeometry=await geometry(page);
   assert(frameGeometry.maxEndpointError<1,`drag frame ${step}: edge endpoint misses its node center by ${frameGeometry.maxEndpointError}px`);
   assert(frameGeometry.maxExpandAnchorError<1,`drag frame ${step}: expand control drifts from its node by ${frameGeometry.maxExpandAnchorError}px`);
   assert(frameGeometry.maxLabelContainmentError<1,`drag frame ${step}: label drifts outside its node by ${frameGeometry.maxLabelContainmentError}px`);
  }
  await page.mouse.up();
  assert(Math.max(...dragErrors)<1,`pointer drag changes the graph's internal shape by ${Math.max(...dragErrors)}px`);
  await scene.press('Home');
  await scene.press('ArrowRight');
  const after=await centers();
  const movement=Object.keys(before).map(id=>Math.hypot(after[id][0]-before[id][0],after[id][1]-before[id][1]));
  assert(Math.max(...movement)<150,`one rotation step jumps ${Math.max(...movement)}px`);
  await scene.press('ArrowLeft');
  const returned=await centers();
  const returnError=Math.max(...Object.keys(before).map(id=>Math.hypot(returned[id][0]-before[id][0],returned[id][1]-before[id][1])));
  assert(returnError<1,`rotation back shifts layout ${returnError}px`);
  for(let count=0;count<3;count++) await scene.press('ArrowRight');
  await scene.press('+');
  await check('desktop rotated and zoomed');
  await page.setViewportSize({width:390,height:844});
  await check('narrow rotated and zoomed');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({multipleBranches:true,initialVisibleLabelOverlaps:initial.overlaps.length,
   initialOverlapPairs:initial.overlaps,
   lockedGraphBody:true,endpointsMatchNodes:true,andOr:true,noDuplicates:true,rotated:true,narrow:true}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
