import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecoveryBudget, claimRecovery, finishRecovery} from '../lib/recovery-budget.mjs';
import {applyPreviewRecovery, searchFixedTerm} from '../lib/term-search.mjs';
const pin = id => ({pin_id:id,status:'available',thumbnail_url:`https://i.pinimg.com/${id}.jpg`});

test('recovery allows one automatic and one manual attempt per card and generation',()=>{
  let budget=createRecoveryBudget('first');
  let claim=claimRecovery(budget,{generation:'first',termId:'body'});
  assert.equal(claim.allowed,true); budget=claim.budget;
  assert.equal(claimRecovery(budget,{generation:'first',termId:'body',kind:'manual'}).allowed,false);
  budget=finishRecovery(budget,{generation:'first',termId:'body'});
  assert.equal(claimRecovery(budget,{generation:'first',termId:'body'}).allowed,false);
  claim=claimRecovery(budget,{generation:'first',termId:'body',kind:'manual'});
  assert.equal(claim.allowed,true); budget=finishRecovery(claim.budget,{generation:'first',termId:'body'});
  assert.equal(claimRecovery(budget,{generation:'first',termId:'body',kind:'manual'}).allowed,false);
  assert.equal(claimRecovery(budget,{generation:'first',termId:'pose'}).allowed,true);
  assert.equal(claimRecovery(budget,{generation:'stale',termId:'body'}).allowed,false);
  assert.equal(claimRecovery(createRecoveryBudget('next'),{generation:'next',termId:'body'}).allowed,true);
});

test('cooldown and access restrictions apply to automatic and manual recovery',()=>{
  let budget=claimRecovery(createRecoveryBudget(1),{generation:1,termId:'body'}).budget;
  budget=finishRecovery(budget,{generation:1,termId:'body',retryAfterSeconds:120,now:1000});
  assert.equal(claimRecovery(budget,{generation:1,termId:'body',kind:'manual',now:2000}).allowed,false);
  assert.equal(claimRecovery(budget,{generation:1,termId:'body',kind:'manual',now:121000}).allowed,true);
  budget=finishRecovery(budget,{generation:1,termId:'body',restricted:true});
  assert.equal(claimRecovery(budget,{generation:1,termId:'body',kind:'manual'}).allowed,false);
});

test('recovery excludes failed IDs and duplicate IDs/images while retaining healthy pins on empty',()=>{
  const term={pins:[pin('1'),pin('1'),pin('2')]};
  assert.deepEqual(applyPreviewRecovery(term,{pins:[]},['2']).pins.map(p=>p.pin_id),['1']);
  const result={pins:[pin('2'),pin('3'),pin('3'),{...pin('4'),thumbnail_url:pin('1').thumbnail_url},pin('5')]};
  assert.deepEqual(applyPreviewRecovery(term,result,['2']).pins.map(p=>p.pin_id),['1','3','5']);
});

test('refill sends bounded exclusions and disables automatic retry',async()=>{
  let count=0;
  await assert.rejects(searchFixedTerm({term_id:'bounded-refill',role:'body'},{
    excludePinIds:Array.from({length:80},(_,i)=>String(i)),maxRetries:0,
    fetchImpl:async(url,options)=>{count++;assert.equal(JSON.parse(options.body).exclude_pin_ids.length,64);
      return {ok:false,status:503,headers:{get:()=>null},json:async()=>({})};},
  }));
  assert.equal(count,1);
});

test('legacy card roles accept canonical composition responses',async()=>{
  for (const role of ['view','layout','composition']) {
    const result=await searchFixedTerm({term_id:`legacy-${role}`,role},{fetchImpl:async()=>({
      ok:true,status:200,json:async()=>({term_id:`legacy-${role}`,role:'composition',pins:[]})})});
    assert.equal(result.role,'composition');
  }
});

test('HTTP failures and cooldown rejection carry recovery metadata',async()=>{
  for (const [status,reason] of [[401,'access_restricted'],[403,'access_restricted'],[429,'rate_limited'],[503,'temporary']]) {
    const term={term_id:`metadata-${status}`,role:'body'};
    const options={maxRetries:0,now:()=>1000,fetchImpl:async()=>({ok:false,status,
      headers:{get:()=> '120'},json:async()=>({})})};
    await assert.rejects(searchFixedTerm(term,options),error=>
      error.status===status && error.search_failure===reason && error.retry_after_seconds===120);
    if(status===429) await assert.rejects(searchFixedTerm(term,options),error=>
      error.status===429 && error.search_failure==='rate_limited' && error.retry_after_seconds===120);
  }
});
