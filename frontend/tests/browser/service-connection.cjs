const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');

(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{})});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  let healthChecks=0,profileCalls=0;
  await page.route('**/service-health',route=>{
   healthChecks+=1;
   return route.fulfill(healthChecks===1?{status:503,json:{status:'unavailable'}}:{json:{status:'ok'}});
  });
  await page.route('**/api/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/api/local/profile'){profileCalls+=1;return route.fulfill({json:{persistent:true}});}
   if(path==='/api/sessions')return route.fulfill({json:{items:[]}});
   return route.abort();
  });
  await page.goto(process.env.APP_BASE||'http://127.0.0.1:3100');
  await page.getByRole('alert').getByText(/대화 서비스에 연결할 수 없습니다/).waitFor();
  assert.equal(profileCalls,0,'unavailable service must not attempt profile mutation');
  assert.equal(await page.getByRole('textbox',{name:'캐릭터 설명'}).isDisabled(),true);
  await page.getByRole('button',{name:'연결 다시 확인'}).click();
  await page.getByRole('textbox',{name:'캐릭터 설명'}).waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.querySelector('#request-text').disabled);
  assert.equal(profileCalls,1);
  assert.equal(healthChecks,2);
  assert.equal(await page.getByRole('alert').count(),0);
  console.log('service connection recovery browser check passed');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
