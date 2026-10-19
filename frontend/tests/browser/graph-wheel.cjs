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
    await page.mouse.move(rect.x+rect.width*.45,rect.y+rect.height*.4);
    await page.mouse.wheel(0,300);
    await page.waitForFunction(()=>document.querySelector('.term-graph').scrollTop>0);
    assert.equal(await scene.getAttribute('data-zoom'),zoom,'wheel down must not zoom');
    await page.mouse.wheel(0,-1000);
    await page.waitForFunction(()=>document.querySelector('.term-graph').scrollTop===0);
    assert.equal(await scene.getAttribute('data-zoom'),zoom,'wheel up must not zoom');
    assert((await page.evaluate(()=>window.wheelPrevented)).every(value=>!value),'native wheel must not be cancelled');
    const yaw=await scene.getAttribute('data-yaw'),box=await scene.boundingBox();
    await page.mouse.move(box.x+box.width*.4,box.y+box.height*.4);await page.mouse.down();
    await page.mouse.move(box.x+box.width*.55,box.y+box.height*.5,{steps:8});await page.mouse.up();
    assert.notEqual(await scene.getAttribute('data-yaw'),yaw,'drag rotation must remain');
    await page.locator('.term-graph-tools > summary').click();
    await page.getByRole('button',{name:'확대',exact:true}).click();
    assert(Number(await scene.getAttribute('data-zoom'))>Number(zoom),'zoom button must remain');
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({wheelZoom:false,nativeScroll:true,wheelNotCancelled:true,dragRotation:true,zoomButton:true,errors}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
