const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const page=await browser.newPage({viewport:{width:1474,height:933},reducedMotion:'reduce'}),errors=[];
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
  const scene=page.locator('.term-graph-scene');
  await scene.press('Home');
  for(let index=0;index<51;index++) await scene.press('ArrowRight');
  for(let index=0;index<2;index++) await scene.press('ArrowDown');

  const audit=await page.evaluate(()=>{
   const scene=document.querySelector('.term-graph-scene'),rect=scene.getBoundingClientRect();
   const nodes=[...scene.querySelectorAll('.term-graph-node,.term-graph-category')].map(element=>{
    const box=element.getBoundingClientRect();
    return {id:element.dataset.nodeId,depth:+element.dataset.depth,z:+getComputedStyle(element).zIndex,
     cx:box.left+box.width/2,cy:box.top+box.height/2,radius:Math.min(box.width,box.height)/2};
   });
   const violations=[],front=[],back=[],endpoint=[],endpointInterior=[];
   const lines=[...scene.querySelectorAll('line')];
   for(const line of lines) {
    const svg=line.closest('svg'),z=+getComputedStyle(svg).zIndex;
    const x1=rect.left+(+line.getAttribute('x1'))*rect.width/1000,y1=rect.top+(+line.getAttribute('y1'))*rect.height/840;
    const x2=rect.left+(+line.getAttribute('x2'))*rect.width/1000,y2=rect.top+(+line.getAttribute('y2'))*rect.height/840;
    const dx=x2-x1,dy=y2-y1,length2=dx*dx+dy*dy;
    if(line.dataset.endpoint) {
     const owner=nodes.find(node=>node.id===line.dataset[line.dataset.endpoint]);
     if(owner) endpoint.push({edge:`${line.dataset.source}->${line.dataset.target}`,side:line.dataset.endpoint,z,nodeZ:owner.z,ok:z<owner.z});
    }
    for(const side of ['source','target']) {
     const owner=nodes.find(node=>node.id===line.dataset[side]);
     if(!owner) continue;
     const middleDistance=Math.hypot((x1+x2)/2-owner.cx,(y1+y2)/2-owner.cy);
     if(middleDistance<owner.radius-1) endpointInterior.push({edge:`${line.dataset.source}->${line.dataset.target}`,side,z,nodeZ:owner.z,
      t0:line.dataset.segmentStart,t1:line.dataset.segmentEnd,middleDistance,radius:owner.radius,ok:z<owner.z});
    }
    const midpointX=(x1+x2)/2,midpointY=(y1+y2)/2;
    const maskedByEndpoint=['source','target'].some(side=>{
     const owner=nodes.find(node=>node.id===line.dataset[side]);
     return owner&&Math.hypot(midpointX-owner.cx,midpointY-owner.cy)<owner.radius-1;
    });
    if(maskedByEndpoint||line.dataset.endpointMask) continue;
    for(const node of nodes) {
     if(node.id===line.dataset.source||node.id===line.dataset.target) continue;
     const t=length2?Math.max(0,Math.min(1,((node.cx-x1)*dx+(node.cy-y1)*dy)/length2)):0;
     const distance=Math.hypot(x1+dx*t-node.cx,y1+dy*t-node.cy);
     if(distance>node.radius+2) continue;
     const edgeDepth=+line.dataset.segmentDepth,delta=edgeDepth-node.depth;
     if(Math.abs(delta)<.01) continue;
     const item={edge:`${line.dataset.source}->${line.dataset.target}`,node:node.id,edgeDepth,nodeDepth:node.depth,z,nodeZ:node.z};
     (delta>0?front:back).push(item);
     if((delta>0)!==(z>node.z)) violations.push(item);
    }
   }
   return {lineCount:lines.length,layerCount:scene.querySelectorAll('.term-graph-edge-layer').length,
    pointerEvents:[...scene.querySelectorAll('.term-graph-edge-layer')].map(layer=>getComputedStyle(layer).pointerEvents),
    violations,front,back,endpoint,endpointInterior,logicalEdges:new Set(lines.map(line=>`${line.dataset.source}->${line.dataset.target}`)).size};
  });
  assert(audit.layerCount>1,'edges are still flattened into one SVG behind every node');
  assert(audit.lineCount>audit.logicalEdges,'long edges were not split into local depth fragments');
  assert(audit.front.length>0,'fixture did not include a front-edge/rear-node crossing');
  assert(audit.back.length>0,'fixture did not include a rear-edge/front-node crossing');
  assert(audit.endpoint.length>0&&audit.endpoint.every(item=>item.ok),'an edge paints through its own endpoint node');
  assert(audit.endpointInterior.length>0&&audit.endpointInterior.every(item=>item.ok),
   `a depth split inside an endpoint footprint escaped above its owner: ${JSON.stringify(audit.endpointInterior.filter(item=>!item.ok).slice(0,8))}`);
  assert(audit.pointerEvents.every(value=>value==='none'),'edge layers intercept node or +/- input');
  assert.deepEqual(audit.violations,[],'edge fragments do not follow perspective depth at node crossings');
  assert.deepEqual(errors,[]);
  if(process.env.SCREENSHOT_PATH) await page.screenshot({path:process.env.SCREENSHOT_PATH,fullPage:true});
  console.log(JSON.stringify({layers:audit.layerCount,fragments:audit.lineCount,logicalEdges:audit.logicalEdges,
   frontCrossings:audit.front.length,backCrossings:audit.back.length,endpointMasking:true,pointerEvents:'none'}));
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
