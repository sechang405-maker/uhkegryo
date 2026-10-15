import test from 'node:test';
import assert from 'node:assert/strict';
import * as server from '../lib/server-conversation.mjs';
const { restoreConversation, loadOlderConversation, listConversationPage } = server;
import * as conversation from '../lib/conversation.mjs';
const { mergeHistoryTurns } = conversation;
const sid='00000000-0000-0000-0000-000000000001';
const job=(id,status='completed')=>({job_id:String(id),session_id:sid,request_text:String(id),job_status:status,result:{answer_text:'answer'}});
const response=body=>({ok:true,status:200,json:async()=>body});
for (const total of [0,20,21,100,1000]) test(`initial ${total} turns makes one bounded history read`,async()=>{
 const calls=[]; const items=Array.from({length:Math.min(total,20)},(_,i)=>job(Math.max(0,total-20)+i));
 const restored=await restoreConversation({sessionId:sid,fetchImpl:async url=>{calls.push(url); if(url.includes('/jobs?'))return response({items,has_more:total>20,next_before_job_id:items[0]?.job_id}); if(url.startsWith('/api/jobs/'))return response(items.at(-1)); return response({session_id:sid});}});
 assert.equal(restored.turns.length,Math.min(total,20)); assert.equal(calls.filter(x=>x.includes('/jobs?')).length,1); assert.ok(calls.some(x=>x.includes('latest=true&limit=20'))); assert.equal(restored.hasMore,total>20);
});
test('older merge preserves current completed and hydrated objects with linear IDs',()=>{
 const current={id:'b',job:{job_status:'completed',hydrated:true}}; const merged=mergeHistoryTurns([current],[{id:'a'},{id:'b',job:{job_status:'running'}}]);
 assert.deepEqual(merged.map(x=>x.id),['a','b']); assert.equal(merged[1],current);
});
test('older page uses owned cursor and preserves pending outside newest page',async()=>{
 const page=await loadOlderConversation({sessionId:sid,beforeJobId:'old',fetchImpl:async url=>{assert.match(url,/before_job_id=old/);return response({items:[job('a')],pending_items:[job('pending','running')],has_more:false});}}); assert.equal(page.turns.length,2);
});
test('sessions page is bounded and reports next offset',async()=>{
 const items=Array.from({length:20},(_,i)=>({session_id:`00000000-0000-0000-0000-${String(i).padStart(12,'0')}`,created_at:'2026-10-01T00:00:00Z'})); let calls=0;
 const page=await listConversationPage({offset:20,fetchImpl:async url=>{calls++;assert.equal(url,'/api/sessions?limit=20&offset=20');return response({items});}}); assert.equal(calls,1); assert.equal(page.nextOffset,40); assert.equal(page.hasMore,true);
});


test('reference outside latest memory page stays separate from rendered turns',async()=>{
 const ref={...job('board'),result:{agent_status:'success',reference_plan:{terms:[{term_id:'body'}]}}};
 const restored=await restoreConversation({sessionId:sid,fetchImpl:async url=> url.includes('/jobs?')?response({items:[job('memory')],reference_item:ref}):url.startsWith('/api/jobs/')?response(url.endsWith('board')?ref:job('memory')):response({session_id:sid})});
 assert.deepEqual(restored.turns.map(x=>x.id),['memory']); assert.equal(restored.referenceJob.job_id,'board');
});
test('latest page pending outside page is chronological and sources retained',async()=>{
 const old=job('pending','running'), latest=job('new');latest.result.sources=[{job_id:'unloaded'}];
 const restored=await restoreConversation({sessionId:sid,fetchImpl:async url=>url.includes('/jobs?')?response({items:[latest],pending_items:[old]}):url.startsWith('/api/jobs/')?response(latest):response({session_id:sid})});
 assert.deepEqual(restored.turns.map(x=>x.id),['pending','new']);assert.equal(restored.turns[1].job.result.sources[0].job_id,'unloaded');
});
test('session pages dedupe without losing active outside first page',async()=>{
 const {mergeSessions}=server;
 const active={session_id:'active'},first={session_id:'first'};
 assert.deepEqual(mergeSessions([active,first],[first,{session_id:'older'}]).map(x=>x.session_id),['active','first','older']);
});

test('in-page board before latest memory answer gets detail hydration',async()=>{
 const board={...job('board'),result:{reference_plan:{terms:[{pins:[{thumbnail_url:'hydrated'}]}]}}};let boardReads=0;
 const restored=await restoreConversation({sessionId:sid,fetchImpl:async url=>{if(url.includes('/jobs?'))return response({items:[job('board'),job('memory')],reference_item:job('board')});if(url.endsWith('/api/jobs/board')){boardReads++;return response(board);}if(url.startsWith('/api/jobs/'))return response(job('memory'));return response({session_id:sid});}});
 assert.equal(boardReads,1);assert.equal(restored.referenceJob.result.reference_plan.terms[0].pins[0].thumbnail_url,'hydrated');
});
test('linear merge orders pending and overlapping pages by timestamp and tie ID',()=>{
 const turn=(id,time)=>({id,job:{created_at:`2026-10-01T00:00:${time}Z`}});
 const pending=turn('p','00');const current=[pending,turn('b','03'),turn('c','03')];
 const older=[turn('a','01'),turn('b','03')];
 const result=mergeHistoryTurns(current,older);assert.deepEqual(result.map(x=>x.id),['p','a','b','c']);assert.equal(result[2],current[1]);
});
