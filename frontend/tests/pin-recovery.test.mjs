import test from 'node:test';
import assert from 'node:assert/strict';
import { searchFixedTerm, applySketchResult, applyPreviewRecovery, retryDelay } from '../lib/term-search.mjs';
import { originalPinLink, pinUnavailableMessage } from '../lib/result-view.mjs';
const good = id => ({pin_id:id,status:'available',thumbnail_url:`https://i.pinimg.com/${id}.jpg`});
const response = (status, result, delay) => ({ok:status===200,status,headers:{get:()=>delay},json:async()=>result});

test('transient failure retries once; restrictions and empty searches never retry', async () => {
  for (const [status, expected] of [[503,2],[403,1],[404,1],[200,1]]) {
    const term={term_id:`retry-${status}`,role:'body'};let calls=0;
    const operation=searchFixedTerm(term,{sleep:async()=>{},fetchImpl:async()=>{calls++;return response(status,{...term,pins:[],reason_codes:['PIN_RESULTS_EMPTY']});}});
    if(status===200) await operation;else await assert.rejects(operation);
    assert.equal(calls,expected);
  }
});
test('429 respects Retry-After including manual retries and HTTP dates', async () => {
  const term={term_id:'limited',role:'body'};let calls=0;
  const options={now:()=>1000,sleep:async()=>assert.fail('long wait must not retry automatically'),fetchImpl:async()=>{calls++;return response(429,{},'120');}};
  await assert.rejects(searchFixedTerm(term,options),/120초/);
  await assert.rejects(searchFixedTerm(term,options),/120초/);
  assert.equal(calls,1);
  assert.equal(retryDelay('Thu, 01 Jan 1970 00:01:00 GMT',0),60000);
});
test('short Retry-After waits before the single retry', async()=>{
  const term={term_id:'short-limit',role:'body'},events=[];
  await searchFixedTerm(term,{sleep:async ms=>events.push(ms),fetchImpl:async()=>{
    events.push('fetch'); return events.length===1?response(429,{},'1'):response(200,{...term,pins:[good('1')]});
  }});
  assert.deepEqual(events,['fetch',1000,'fetch']);
});
test('partial results survive and preview recovery retains every healthy old pin',()=>{
  const term={pins:[good('1'),{pin_id:'e1_old',status:'unavailable',failure_reason:'expired'}]};
  const result={pins:[good('2')],reason_codes:['PIN_SEARCH_UNAVAILABLE']};
  assert.equal(applySketchResult(term,result).pins.length,1);
  assert.deepEqual(applyPreviewRecovery(term,result).pins.map(p=>p.pin_id),['1','2']);
  assert.deepEqual(applyPreviewRecovery(term,{pins:[],reason_codes:['PIN_RESULTS_EMPTY']}).pins,[good('1')]);
  assert.equal(term.pins[0].pin_id,'1');
});
test('expired and restricted pins have distinct notices and only canonical original links',()=>{
  assert.match(pinUnavailableMessage({failure_reason:'expired'}),/만료/);
  assert.match(pinUnavailableMessage({failure_reason:'access_restricted'}),/접근이 제한/);
  assert.equal(originalPinLink({pin_id:'123',pin_url:'javascript:bad'}),'https://www.pinterest.com/pin/123/');
  assert.equal(originalPinLink({pin_id:'../bad'}),null);
});
