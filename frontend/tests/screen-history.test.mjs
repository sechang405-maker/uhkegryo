import test from 'node:test';
import assert from 'node:assert/strict';
import { createScreenHistory } from '../lib/screen-history.mjs';

function fixture(initial={screen:'home',draft:'',selected:[]}) {
 let screen=initial,index=0,next={__NA:true,tree:['next']},listener;
 const entries=[{state:next}];
 const history={get state(){return entries[index].state;},replaceState(state){entries[index]={state};},pushState(state){entries.splice(++index);entries.push({state});}};
 const target={addEventListener(name,fn){listener=fn;},removeEventListener(name,fn){if(listener===fn)listener=null;}};
 const controller=createScreenHistory({history,target,read:()=>screen,restore:s=>{screen=s;},fallback:()=>({screen:'home'}),keyForSnapshot:s=>s.screen==='home'?'home':null,scope:'test'});
 return {controller,entries,history,get screen(){return screen;},set screen(v){screen=v;},go(delta){index+=delta;listener({state:history.state});},get index(){return index;}};
}

test('records real transitions, preserves drafts/selections/results and supports forward without pushing',()=>{
 const f=fixture();f.screen={screen:'home',draft:'초안',selected:['term-a']};
 f.controller.visit('term:a');f.screen={screen:'results',draft:'초안',selected:['term-a'],pins:['one']};f.controller.capture();
 f.controller.visit('turn:b');f.screen={screen:'history',draft:'다른 초안',pins:['two']};f.controller.capture();
 f.go(-1);assert.deepEqual(f.screen.pins,['one']);assert.equal(f.screen.draft,'초안');
 f.go(-1);assert.deepEqual(f.screen.selected,['term-a']);assert.equal(f.screen.screen,'home');
 f.go(1);assert.deepEqual(f.screen.pins,['one']);assert.equal(f.entries.length,3);
 assert.equal(f.history.state.__NA,true);assert.deepEqual(f.history.state.tree,['next']);
 assert.equal(JSON.stringify(f.history.state).includes('초안'),false,'private snapshots stay in memory, not browser history');
});
test('same screen does not duplicate entries and a new visit truncates forward history',()=>{
 const f=fixture();f.controller.visit('term:a');f.screen={screen:'results'};f.controller.capture();
 assert.equal(f.controller.visit('term:a'),false);assert.equal(f.entries.length,2);
 f.controller.visit('turn:b');f.controller.capture();f.go(-1);f.controller.visit('term:c');
 assert.equal(f.entries.length,3);assert.equal(f.index,2);
});
test('reload replaces only the current entry and unknown earlier entries safely return home',()=>{
 const f=fixture();f.controller.visit('term:a');f.screen={screen:'results'};f.controller.capture();f.controller.dispose();
 const controller=createScreenHistory({history:f.history,target:{addEventListener(){},removeEventListener(){}},read:()=>({screen:'home'}),restore(){},fallback:()=>({screen:'home'}),scope:'reload'});
 assert.equal(f.entries.length,2);assert.equal(f.history.state.__uhScreen.scope,'reload');controller.dispose();
});
test('deleted sessions are invalidated and traversal never restores deleted content',()=>{
 const f=fixture();f.controller.visit('session:a');f.screen={screen:'history',sessionId:'deleted',turns:['private']};f.controller.capture();
 f.controller.visit('home');f.screen={screen:'home'};f.controller.capture();f.controller.forgetSession('deleted');
 f.go(-1);assert.deepEqual(f.screen,{screen:'home'});assert.equal(f.entries.length,3);
});

test('an asynchronously restored initial result is a real screen before navigating home',()=>{
 const f=fixture({screen:'restoring'});f.screen={screen:'results',pins:['initial']};f.controller.capture();
 assert.equal(f.controller.visit('home'),true);f.screen={screen:'home'};f.controller.capture();
 f.go(-1);assert.deepEqual(f.screen.pins,['initial']);
 const home=fixture();assert.equal(home.controller.visit('home'),false);assert.equal(home.entries.length,1);
});
