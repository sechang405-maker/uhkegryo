import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {mergeHistoryTurns} from '../lib/conversation.mjs';
const source=readFileSync(new URL('../app/page.jsx',import.meta.url),'utf8');
const start=source.indexOf('  async function loadOlder()');
const end=source.indexOf('  useEffect(',start);
function context(){
 const state={turns:[{id:'current',job:{hydrated:true}}],page:null,loading:false,error:''};let release;
 const c={AbortController,olderLoading:false,historyPage:{hasMore:true,nextBeforeJobId:'cursor'},sessionLoadRef:{current:1},sessionIdRef:{current:'session'},historyController:{current:null},chatScrollRef:{current:{scrollTop:50,scrollHeight:100}},prependAnchor:{current:null},mergeHistoryTurns,
 loadOlderConversation:()=>new Promise(resolve=>{release=resolve}),setOlderLoading:v=>state.loading=v,setOlderError:v=>state.error=v,setHistoryPage:v=>state.page=v,setTurns:f=>state.turns=f(state.turns)};
 vm.createContext(c);vm.runInContext(source.slice(start,end)+'\nthis.load=loadOlder',c);
 return {c,state,release:page=>release(page)};
}
test('prepend captures viewport without changing selection, gallery, or draft',async()=>{
 const {c,state,release}=context();const pending=c.load();release({turns:[{id:'old'},{id:'current',job:{hydrated:false}}],hasMore:false});await pending;
 assert.deepEqual(state.turns.map(x=>x.id),['old','current']);assert.equal(state.turns[1].job.hydrated,true);assert.equal(c.prependAnchor.current.top,50);assert.equal(c.prependAnchor.current.height,100);assert.equal(state.loading,false);
});
test('late page after session switch cannot prepend or update cursor',async()=>{
 const {c,state,release}=context();const pending=c.load();c.sessionLoadRef.current++;c.sessionIdRef.current='other';c.historyController.current.abort();release({turns:[{id:'old'}],hasMore:false});await pending;
 assert.deepEqual(state.turns.map(x=>x.id),['current']);assert.equal(state.page,null);assert.equal(c.prependAnchor.current,null);
});
