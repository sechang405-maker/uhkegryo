import test from 'node:test';
import assert from 'node:assert/strict';
import {deleteConversation,ensureLocalProfile,DELETE_CONFIRM} from '../lib/server-conversation.mjs';
import {createDemoSessionStore} from '../lib/portfolio-demo-sessions.mjs';
const id='00000000-0000-0000-0000-000000000001';
test('delete uses credentials and action header; success does not require JSON',async()=>{
 let called=false;
 await deleteConversation(id,{fetchImpl:async(url,options)=>{called=true;assert.equal(url,'/api/sessions/'+id);assert.equal(options.method,'DELETE');assert.equal(options.credentials,'include');assert.equal(options.headers['X-Conversation-Action'],'delete');return {status:204};}});
 assert.equal(called,true);assert.match(DELETE_CONFIRM,/영구 삭제/);assert.match(DELETE_CONFIRM,/복구할 수 없습니다/);
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
test('demo deletion persists without resurrecting removed samples',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 const store=createDemoSessionStore(storage), first=store.current().session_id, second=store.create().session_id;
 store.remove(first);assert.equal(store.list().length,1);assert.equal(store.current().session_id,second);
 const blank=store.remove(second);assert.equal(blank.turns.length,0);
 const restored=createDemoSessionStore(storage);assert.equal(restored.current().turns.length,0);assert.ok(!restored.list().some(s=>s.session_id===first||s.session_id===second));
});
test('all retained conversations remain accessible beyond the first page', async () => {
  const { listConversations } = await import('../lib/server-conversation.mjs');
  const calls=[];
  const items=Array.from({length:101},(_,i)=>({session_id:`00000000-0000-4000-8000-${String(i).padStart(12,'0')}`,created_at:'2026-10-14T00:00:00Z'}));
  const result=await listConversations({fetchImpl:async(url)=>{
    calls.push(url); const offset=Number(new URL(url,'http://test').searchParams.get('offset'));
    return {ok:true,status:200,json:async()=>({items:items.slice(offset,offset+100)})};
  }});
  assert.equal(result.length,101); assert.equal(calls.length,2);
});
