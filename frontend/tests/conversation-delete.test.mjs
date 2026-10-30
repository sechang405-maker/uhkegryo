import test from 'node:test';
import assert from 'node:assert/strict';
import {deleteConversation,ensureConversationProfile,ensureLocalProfile,ensureServiceAvailable,SERVICE_UNAVAILABLE_ERROR} from '../lib/server-conversation.mjs';
import {createDemoSessionStore} from '../lib/portfolio-demo-sessions.mjs';
const id='00000000-0000-0000-0000-000000000001';
test('delete uses credentials and action header; success does not require JSON',async()=>{
 let called=false;
 await deleteConversation(id,{fetchImpl:async(url,options)=>{called=true;assert.equal(url,'/api/sessions/'+id);assert.equal(options.method,'DELETE');assert.equal(options.credentials,'include');assert.equal(options.headers['X-Conversation-Action'],'delete');return {status:204};}});
 assert.equal(called,true);
});
test('failed and busy deletion give actionable errors',async()=>{
 await assert.rejects(deleteConversation(id,{fetchImpl:async()=>({status:409})}),/처리 중/);
 await assert.rejects(deleteConversation(id,{fetchImpl:async()=>({status:503})}),/기록을 유지/);
 await assert.rejects(deleteConversation('../other',{fetchImpl:()=>assert.fail('invalid id')}));
});
test('profile bootstrap is explicit and errors are not silently ignored',async()=>{
 assert.equal(await ensureLocalProfile({fetchImpl:async(url,o)=>{assert.equal(url,'/api/local/profile');assert.equal(o.method,'POST');assert.equal(o.headers['X-Conversation-Action'],'profile');return {ok:true,json:async()=>({persistent:true})};}}),true);
 await assert.rejects(ensureLocalProfile({fetchImpl:async()=>({ok:false})}));
});
test('portfolio conversation startup never calls the blocked local profile route',async()=>{
 let called=false;
 const persistent=await ensureConversationProfile({portfolioMode:true,fetchImpl:async()=>{called=true;throw new Error('must not call');}});
 assert.equal(persistent,false);
 assert.equal(called,false);
});
test('service availability is checked without mutating data and reports a precise reconnect error',async()=>{
 let request;
 assert.equal(await ensureServiceAvailable({fetchImpl:async(...args)=>{
  request=args;return {ok:true,json:async()=>({status:'ok'})};
 }}),true);
 assert.equal(request[0],'/service-health');
 assert.equal(request[1].method,'GET');
 assert.equal(request[1].cache,'no-store');
 for(const response of [
  async()=>({ok:false,status:503}),
  async()=>({ok:true,json:async()=>({status:'starting'})}),
  async()=>{throw new TypeError('fetch failed')},
 ]) await assert.rejects(ensureServiceAvailable({fetchImpl:response}),error=>error.message===SERVICE_UNAVAILABLE_ERROR);
});
test('demo deletion persists without resurrecting removed samples',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 const store=createDemoSessionStore(storage), first=store.current().session_id, second=store.create().session_id;
 store.remove(first);assert.equal(store.list().length,1);assert.equal(store.current().session_id,second);
 const blank=store.remove(second);assert.equal(blank.turns.length,0);
 const restored=createDemoSessionStore(storage);assert.equal(restored.current().turns.length,0);assert.ok(!restored.list().some(s=>s.session_id===first||s.session_id===second));
});
test('all retained conversations remain accessible beyond the first page', async () => {
  const { listConversationPage, mergeSessions } = await import('../lib/server-conversation.mjs');
  const calls=[];
  const items=Array.from({length:101},(_,i)=>({session_id:`00000000-0000-4000-8000-${String(i).padStart(12,'0')}`,created_at:'2026-10-14T00:00:00Z'}));
  let result=[],offset=0;
  for (;;) {
    const page=await listConversationPage({offset,fetchImpl:async(url)=>{
      calls.push(url); const start=Number(new URL(url,'http://test').searchParams.get('offset'));
      return {ok:true,status:200,json:async()=>({items:items.slice(start,start+20)})};
    }});
    result=mergeSessions(result,page.items);
    if(!page.hasMore) break;
    offset=page.nextOffset;
  }
  assert.equal(result.length,101); assert.equal(calls.length,6);
});
