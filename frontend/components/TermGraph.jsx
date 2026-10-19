'use client';

import { useMemo, useRef, useState } from 'react';
import { buildTermGraph, projectGraph, INITIAL_VIEW, clamp } from '../lib/term-graph.mjs';

export default function TermGraph({terms, selectedIds, onToggle, onAdd, onSearch}) {
  const graph=useMemo(()=>buildTermGraph(terms),[terms]);
  const [view,setView]=useState(INITIAL_VIEW);
  const [list,setList]=useState(false);
  const [focusedId,setFocusedId]=useState(terms[0]?.term_id);
  const [notice,setNotice]=useState('');
  const gesture=useRef(null);
  const pointers=useRef(new Map());
  const suppressClick=useRef(false);
  const focused=terms.find(term=>term.term_id===focusedId);
  const selected=terms.filter(term=>selectedIds.includes(term.term_id));
  const points=useMemo(()=>projectGraph(graph,view),[graph,view]);
  function rotate(dx,dy) { setView(v=>({...v,yaw:v.yaw+dx,pitch:clamp(v.pitch+dy,-1.2,1.2)})); }
  function zoom(delta) { setView(v=>({...v,zoom:clamp(v.zoom+delta,.65,1.6)})); }
  function start(event) {
    if(event.button!==0) return;
    pointers.current.set(event.pointerId,{x:event.clientX,y:event.clientY});
    suppressClick.current=false;
    const pair=[...pointers.current.values()];
    gesture.current={x:event.clientX,y:event.clientY,view,
      distance:pair.length===2?Math.hypot(pair[0].x-pair[1].x,pair[0].y-pair[1].y):null};
    // Keep ordinary button clicks intact; capture on the original target for drag outside.
    event.target.setPointerCapture?.(event.pointerId);
  }
  function move(event) {
    if(!pointers.current.has(event.pointerId)||!gesture.current) return;
    pointers.current.set(event.pointerId,{x:event.clientX,y:event.clientY});
    const pair=[...pointers.current.values()],g=gesture.current;
    if(pair.length===2 && g.distance) {
      suppressClick.current=true;
      const distance=Math.hypot(pair[0].x-pair[1].x,pair[0].y-pair[1].y);
      g.latest={...g.view,zoom:clamp(g.view.zoom*distance/g.distance,.65,1.6)};
      setView(g.latest);
    } else if(pair.length===1) {
      const dx=event.clientX-g.x,dy=event.clientY-g.y;
      if(Math.hypot(dx,dy)<5) return;
      suppressClick.current=true;
      g.latest={...g.view,yaw:g.view.yaw+dx*.006,pitch:clamp(g.view.pitch+dy*.006,-1.2,1.2)};
      setView(g.latest);
    }
  }
  function end(event) {
    // pointerup is followed by lostpointercapture; rebase only once.
    if(!pointers.current.delete(event.pointerId)) return;
    const remaining=pointers.current.values().next().value;
    gesture.current=remaining ? {...remaining,view:gesture.current?.latest||view,distance:null} : null;
  }
  function pick(id) { if(!suppressClick.current) setFocusedId(id); }
  function key(event) {
    if(event.target!==event.currentTarget) return;
    const actions={ArrowLeft:()=>rotate(-.16,0),ArrowRight:()=>rotate(.16,0),ArrowUp:()=>rotate(0,-.16),ArrowDown:()=>rotate(0,.16),'+':()=>zoom(.1),'=':()=>zoom(.1),'-':()=>zoom(-.1),Home:()=>setView(INITIAL_VIEW)};
    if(actions[event.key]) {event.preventDefault();actions[event.key]();}
  }
  return <section className="term-graph" aria-label="예시 용어 3D 그래프">
    <header className="term-graph-heading">
      <div><span className="term-graph-eyebrow">UH · 용어 탐색</span><h1>그림의 조건을 연결해 보세요</h1>
        <p>선은 카테고리 소속을 뜻해요. 같은 카테고리에서도 여러 용어를 고를 수 있어요.</p></div>
      <button type="button" aria-pressed={list} onClick={()=>{setList(!list);suppressClick.current=false;}}>{list?'3D 보기':'목록 보기'}</button>
    </header>
    {list ? <div className="term-graph-list" aria-label="전체 예시 용어 목록">
      {graph.nodes.filter(n=>!n.term).map(category=><fieldset key={category.id}><legend>{category.label}</legend>
        {graph.nodes.filter(n=>n.term && n.role===category.role).map(node=><div key={node.id}>
          <label><input type="checkbox" checked={selectedIds.includes(node.id)} onChange={()=>onToggle(node.id)}/>{node.label}</label>
          <button type="button" aria-label={`${node.label} 설명 보기`} onClick={()=>setFocusedId(node.id)}>설명</button>
        </div>)}
      </fieldset>)}
    </div> : <>
      <div className="term-graph-controls" role="group" aria-label="그래프 회전 조절">
        <button type="button" aria-label="왼쪽으로 회전" onClick={()=>rotate(-.2,0)}>↶</button>
        <button type="button" aria-label="오른쪽으로 회전" onClick={()=>rotate(.2,0)}>↷</button>
        <button type="button" aria-label="축소" disabled={view.zoom<=.65} onClick={()=>zoom(-.15)}>−</button>
        <span aria-live="off">{Math.round(view.zoom*100)}%</span>
        <button type="button" aria-label="확대" disabled={view.zoom>=1.6} onClick={()=>zoom(.15)}>+</button>
        <button type="button" onClick={()=>setView(INITIAL_VIEW)}>회전 초기화</button>
      </div>
      <div className="term-graph-scene" tabIndex={0} role="group" aria-label="회전 가능한 용어 공간"
        aria-describedby="term-graph-help" onKeyDown={key} onPointerDown={start} onPointerMove={move}
        onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
        data-yaw={view.yaw.toFixed(3)} data-pitch={view.pitch.toFixed(3)} data-zoom={view.zoom.toFixed(2)}>
        <svg viewBox="0 0 1000 700" preserveAspectRatio="none" aria-hidden="true">
          {graph.edges.map(edge=><line key={edge.target} x1={points[edge.source].x} y1={points[edge.source].y}
            x2={points[edge.target].x} y2={points[edge.target].y}
            style={{opacity:(points[edge.source].opacity+points[edge.target].opacity)/2*.55}}
            className={focusedId===edge.target?'is-focused':''}/>)}
        </svg>
        {graph.nodes.map(node=>{
          const p=points[node.id];
          const style={left:`${p.x/10}%`,top:`${p.y/7}%`,zIndex:Math.round(p.depth+500),opacity:p.opacity,'--node-scale':p.scale};
          return node.term ? <button type="button" key={node.id} style={style} className="term-graph-node"
            data-focused={focusedId===node.id} data-selected={selectedIds.includes(node.id)}
            data-node-id={node.id} data-depth={p.depth.toFixed(3)} data-distant={p.depth < -40}
            aria-label={`${node.label} 설명 보기`} aria-pressed={focusedId===node.id}
            onFocus={()=>{suppressClick.current=false;setFocusedId(node.id);}} onClick={()=>pick(node.id)}>
            <span className="term-graph-dot" aria-hidden="true">{selectedIds.includes(node.id)?'✓':''}</span>
            <span className="term-graph-label">{node.label}</span>
          </button> : <span key={node.id} style={style} data-node-id={node.id} data-depth={p.depth.toFixed(3)} className="term-graph-category">{node.label}</span>;
        })}
      </div>
      <p id="term-graph-help" className="term-graph-help">드래그로 회전 · 버튼/두 손가락으로 확대 · 공간에 초점을 두고 방향키로 회전 · Tab으로 용어 이동</p>
    </>}
    {focused && <article className="term-graph-detail" aria-label="선택한 용어 설명">
      <div aria-live="polite"><h2>{focused.label_ko}</h2><p>{focused.plain_meaning_ko}</p></div>
      <div className="term-graph-actions">
        <button type="button" aria-pressed={selectedIds.includes(focused.term_id)} onClick={()=>onToggle(focused.term_id)}>{selectedIds.includes(focused.term_id)?'선택 해제':'용어 선택'}</button>
        <button type="button" onClick={()=>onSearch(focused)}>레퍼런스 검색</button>
      </div>
    </article>}
    <footer className="term-graph-selection">
      <div className="term-graph-chips" aria-label="선택한 용어">
        {selected.length ? selected.map(term=><button key={term.term_id} type="button" aria-label={`${term.label_ko} 선택 해제`} onClick={()=>onToggle(term.term_id)}>{term.label_ko} <span aria-hidden="true">×</span></button>) : <span>용어를 고른 뒤 설명을 입력에 추가해 보세요.</span>}
      </div>
      <button type="button" disabled={!selected.length} onClick={()=>setNotice(onAdd(selected)?'선택한 용어를 입력에 추가했어요.':'500자 이내로 추가할 수 있도록 입력을 줄여 주세요.')}>선택 {selected.length}개 입력에 추가</button>
      <p role="status">{notice}</p>
    </footer>
  </section>;
}
