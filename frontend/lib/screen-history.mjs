// Browser entries contain opaque IDs only. Drafts/results remain in this page's memory.
export function createScreenHistory({history,target,read,restore,fallback,keyForSnapshot,scope=globalThis.crypto.randomUUID()}) {
 const entries=new Map(),deletedSessions=new Set();
 let sequence=0,current='0';
 const marker=id=>({...history.state,__uhScreen:{scope,id}});
 const safe=snapshot=>deletedSessions.has(snapshot?.sessionId)?fallback():snapshot;
 function capture() {
  const entry=entries.get(current);
  if(entry) {
   entry.snapshot=safe(read());
   entry.key=keyForSnapshot?.(entry.snapshot)||entry.key;
  }
 }
 entries.set(current,{key:keyForSnapshot?.(read())||'initial',snapshot:read()});
 history.replaceState(marker(current),'');
 function pop(event) {
  capture();
  const mark=event.state?.__uhScreen;
  current=mark?.scope===scope?mark.id:null;
  const snapshot=entries.get(current)?.snapshot;
  restore(snapshot?safe(snapshot):fallback());
 }
 target.addEventListener('popstate',pop);
 return {
  capture,
  visit(key) {
   capture();
   if(entries.get(current)?.key===key)return false;
   current=String(++sequence);
   entries.set(current,{key,snapshot:read()});
   history.pushState(marker(current),'');
   return true;
  },
  forgetSession(sessionId) {
   deletedSessions.add(sessionId);
   for(const [id,entry] of entries)if(entry.snapshot?.sessionId===sessionId)entries.delete(id);
  },
  dispose(){target.removeEventListener('popstate',pop);entries.clear();},
 };
}
