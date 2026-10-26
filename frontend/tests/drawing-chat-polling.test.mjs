import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {resultTerms} from '../lib/result-view.mjs';
import {upsertTurn} from '../lib/conversation.mjs';
import {createMobileResultOrigin,resolveMobileResult} from '../lib/mobile-result-flow.mjs';
const source=readFileSync(new URL('../app/page.jsx',import.meta.url),'utf8');
const begin=source.indexOf('    const latestTurn = turns.at(-1);');
const end=source.indexOf('    pollerRef.current = poller;',begin);
function setup(originScreenId){
 const screenGeneration=originScreenId??1;
 const state={turns:[{id:'latest',screen_generation:screenGeneration,mobile_result_origin:createMobileResultOrigin({requestId:'latest',sessionId:'session',screenGeneration,panelRevision:0})}],board:'home',panel:'conversation',gallery:null,notice:null};let update,fail;
 const context={turns:state.turns,sessionIdRef:{current:'session'},screenGenerationRef:{current:1},mobilePanelRevisionRef:{current:0},resultTerms,upsertTurn,resolveMobileResult,
  resumeConversation:(_turns,options)=>{update=options.onUpdate;fail=options.onError;return {};},
  setTurns:fn=>{state.turns=fn(state.turns);},refreshSessions:()=>{},refreshCurrentConditions:()=>{},
  gallerySelectionRef:{current:{live:job=>{if(resultTerms(job).length)state.gallery=job;}}},
  setBoardView:value=>{state.board=value;},setMobilePanel:value=>{state.panel=value;},
  setMobileResultNotice:value=>{state.notice=typeof value==='function'?value(state.notice):value;},
  setTermSearch:()=>{},setTermGuide:()=>{},resetSketchSearches:()=>{},setPollError:()=>{},stopTurnPolling:()=>{}};
 vm.runInNewContext(source.slice(begin,end),context);return {state,context,update,fail};
}
const turn=status=>({id:'latest',job:{job_id:'latest',session_id:'session',job_status:'completed',result:{agent_status:status,answer_text:'Contextual response',reference_plan:status==='success'?{terms:[{term_id:'pose'}]}:null}}});
test('chat and clarification update answers while keeping the board and mobile conversation',()=>{
 for(const status of ['drawing_chat','needs_clarification','memory_answer']){const {state,update}=setup();update(turn(status));assert.equal(state.turns[0].job.result.agent_status,status);assert.equal(state.board,'home');assert.equal(state.panel,'conversation');assert.equal(state.gallery,null);}
});
test('explicit references replace the board and show the mobile reference tab',()=>{
 const {state,update}=setup();update(turn('success'));assert.equal(state.board,'results');assert.equal(state.panel,'reference');assert.equal(state.gallery.job_id,'latest');
});
test('an explicit mobile tab choice prevents takeover and leaves a result action',()=>{
 const {state,context,update}=setup();context.mobilePanelRevisionRef.current++;update(turn('success'));
 assert.equal(state.board,'results');assert.equal(state.panel,'conversation');assert.equal(state.gallery.job_id,'latest');
 assert.equal(state.notice.targetPanel,'reference');assert.equal(state.notice.requestId,'latest');
});
test('a polling failure does not steal an explicitly selected panel and points back to the error',()=>{
 const {state,context,fail}=setup();state.panel='reference';context.mobilePanelRevisionRef.current++;
 fail('latest','잠시 후 다시 시도해 주세요.');
 assert.equal(state.panel,'reference');assert.equal(state.notice.targetPanel,'conversation');assert.equal(state.notice.requestId,'latest');
});
test('late reference completion after navigation updates the conversation without taking over the screen',()=>{
 const {state,context,update}=setup();context.screenGenerationRef.current++;update(turn('success'));assert.equal(state.turns[0].job.result.agent_status,'success');assert.equal(state.board,'home');assert.equal(state.panel,'conversation');assert.equal(state.gallery,null);
});

test('accepted job keeps submission origin when the poller starts after another navigation',()=>{
 const {state,update}=setup(0);update({...turn('success'),screen_generation:0});assert.equal(state.turns[0].job.result.agent_status,'success');assert.equal(state.board,'home');assert.equal(state.panel,'conversation');assert.equal(state.gallery,null);
});

test('restoring a pending request reconnects only requests belonging to that saved screen',()=>{
 const start=source.indexOf('    setTurns(snapshot.turns');const end=source.indexOf('    setHistoryPage(snapshot.historyPage);',start);
 const pending=(id,origin)=>({id,screen_generation:origin,job:{job_status:'running'}});
 const snapshot={screenGeneration:10,turns:[pending('owned',10),pending('foreign',9),{id:'done',screen_generation:10,job:{job_status:'completed'}}]};
 let restored;vm.runInNewContext(source.slice(start,end),{snapshot,screenGenerationRef:{current:22},isTurnPending:turn=>turn.job.job_status==='running',setTurns:turns=>{restored=turns;}});
 assert.equal(restored[0].screen_generation,22);assert.equal(restored[1].screen_generation,9);assert.equal(restored[2].screen_generation,10);
});

test('reconnected pending request restarts polling even when its job ID stays the same',()=>{
 const line=source.split('\n').find(line=>line.includes('const pendingTurnIds ='));
 const key=origin=>vm.runInNewContext(line+'\npendingTurnIds;',{turns:[{id:'same-job',screen_generation:origin}],isTurnPending:()=>true});
 assert.notEqual(key(10),key(22));
});
