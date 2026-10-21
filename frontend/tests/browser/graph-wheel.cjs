// Browser regression: APP_BASE, PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE are optional.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/api/**',route=>{
      const path=new URL(route.request().url()).pathname;
      if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
      if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
      return route.abort();
    });
    await page.goto(process.env.APP_BASE || 'http://127.0.0.1:3100');
    await page.waitForLoadState('networkidle');
    const graph=page.locator('.term-graph'),scene=page.locator('.term-graph-scene');
    await scene.waitFor();
    await page.evaluate(()=>{window.wheelPrevented=[];document.addEventListener('wheel',event=>window.wheelPrevented.push(event.defaultPrevented),{passive:true});});
    const zoom=await scene.getAttribute('data-zoom'),rect=await scene.boundingBox();
    assert.equal(await graph.evaluate(element=>element.scrollHeight<=element.clientHeight+1),true,'central graph must fit without vertical scrolling');
    await page.mouse.move(rect.x+rect.width*.45,rect.y+rect.height*.4);
    await page.mouse.wheel(0,300);
    await page.waitForFunction(previous=>+document.querySelector('.term-graph-scene').dataset.zoom<+previous,zoom);
    const zoomedOut=await scene.getAttribute('data-zoom');
    assert.equal(await graph.evaluate(element=>element.scrollTop),0,'wheel zoom must not scroll the central graph');
    await page.mouse.wheel(0,-1000);
    await page.waitForFunction(previous=>+document.querySelector('.term-graph-scene').dataset.zoom>+previous,zoomedOut);
    assert((await page.evaluate(()=>window.wheelPrevented)).every(Boolean),'wheel over the graph must be consumed by camera zoom');
    const yaw=await scene.getAttribute('data-yaw'),box=await scene.boundingBox();
    await page.mouse.move(box.x+box.width*.4,box.y+box.height*.4);await page.mouse.down();
    await page.mouse.move(box.x+box.width*.55,box.y+box.height*.5,{steps:8});await page.mouse.up();
    assert.notEqual(await scene.getAttribute('data-yaw'),yaw,'drag rotation must remain');
    await page.locator('.term-graph-tools > summary').click();
    await page.getByRole('button',{name:'확대',exact:true}).click();
    assert(Number(await scene.getAttribute('data-zoom'))>Number(zoom),'zoom button must remain');
    const mobile=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
    await mobile.route('**/api/**',route=>{
      const path=new URL(route.request().url()).pathname;
      if(path==='/api/local/profile') return route.fulfill({json:{persistent:false}});
      if(path==='/api/sessions') return route.fulfill({json:{items:[]}});
      return route.abort();
    });
    await mobile.goto(process.env.APP_BASE || 'http://127.0.0.1:3100');
    await mobile.waitForLoadState('networkidle');
    await mobile.locator('.term-graph-list').waitFor();
    await mobile.locator('.term-graph-view-toggle > button').click();
    const mobileScene=mobile.locator('.term-graph-scene');
    await mobileScene.waitFor();
    const mobileZoom=await mobileScene.getAttribute('data-zoom'),mobileRect=await mobileScene.boundingBox();
    await mobile.mouse.move(mobileRect.x+mobileRect.width*.5,mobileRect.y+mobileRect.height*.45);
    await mobile.mouse.wheel(0,240);
    await mobile.waitForFunction(previous=>+document.querySelector('.term-graph-scene').dataset.zoom<+previous,mobileZoom);
    await mobile.close();
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({wheelZoom:true,mobileWheelZoom:true,centralNoScroll:true,wheelCancelled:true,dragRotation:true,zoomButton:true,errors}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
