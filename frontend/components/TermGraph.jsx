'use client';

import { Fragment, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { buildExpandedTermGraph, projectGraph, INITIAL_VIEW, clamp, toggleExpanded } from '../lib/term-graph.mjs';

export default function TermGraph({terms, catalogTerms=terms, selectedIds, onToggle, onAdd, onSearch, focusedId, onFocus, list, onListChange}) {
  const [expandedIds,setExpandedIds]=useState([]);
  const graph=useMemo(()=>buildExpandedTermGraph(terms,catalogTerms,expandedIds),[terms,catalogTerms,expandedIds]);
  const [view,setView]=useState(INITIAL_VIEW);
  const [notice,setNotice]=useState('');
  const [sceneSize,setSceneSize]=useState({width:1000,height:700});
  const sceneRef=useRef(null);
  const gesture=useRef(null);
  const pointers=useRef(new Map());
  const suppressClick=useRef(false);
  const focused=catalogTerms.find(term=>term.term_id===focusedId);
  const selected=catalogTerms.filter(term=>selectedIds.includes(term.term_id));
  const points=useMemo(()=>projectGraph(graph,view,sceneSize),[graph,view,sceneSize]);
  useLayoutEffect(()=>{
    const scene=sceneRef.current;
    if(!scene) return;
    const update=()=>{
      const {width,height}=scene.getBoundingClientRect();
      if(width<=0||height<=0) return;
      setSceneSize(previous=>Math.abs(previous.width-width)<.5&&Math.abs(previous.height-height)<.5?previous:{width,height});
    };
    update();
    const observer=new ResizeObserver(update);
    observer.observe(scene);
    return ()=>observer.disconnect();
  },[list]);
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
  function pick(id) { if(!suppressClick.current) onToggle(id); }
  function expand(event,id) {
    event.preventDefault();event.stopPropagation();suppressClick.current=false;
    setExpandedIds(ids=>toggleExpanded(ids,id));
  }
  function key(event) {
    if(event.target!==event.currentTarget) return;
    const actions={ArrowLeft:()=>rotate(-.16,0),ArrowRight:()=>rotate(.16,0),ArrowUp:()=>rotate(0,-.16),ArrowDown:()=>rotate(0,.16),'+':()=>zoom(.1),'=':()=>zoom(.1),'-':()=>zoom(-.1),Home:()=>setView(INITIAL_VIEW)};
    if(actions[event.key]) {event.preventDefault();actions[event.key]();}
  }
  return <section className="term-graph" aria-label="예시 용어 3D 그래프">
    <div className="term-graph-view-toggle">
      <button type="button" aria-pressed={list} onClick={()=>{onListChange(!list);suppressClick.current=false;}}>{list?'3D 보기':'목록 보기'}</button>
    </div>
    {list ? <div className="term-graph-list" aria-label="전체 예시 용어 목록">
      {graph.nodes.filter(n=>!n.term).map(category=><fieldset key={category.id}><legend>{category.label}</legend>
        {graph.nodes.filter(n=>n.term && n.role===category.role).map(node=><div key={node.id}>
          <label><input type="checkbox" checked={selectedIds.includes(node.id)} onChange={()=>onToggle(node.id)}/>{node.label}</label>
          <span className="term-graph-list-actions">
            {node.expandable && <button type="button" aria-label={`${node.label}: 이 조건이 필요한 세부 용어 ${expandedIds.includes(node.id)?'접기':'펼치기'}`}
              aria-expanded={expandedIds.includes(node.id)} onClick={(event)=>expand(event,node.id)}>{expandedIds.includes(node.id)?'−':'+'}</button>}
            <button type="button" aria-label={`${node.label} 설명 보기`} onClick={()=>onFocus(node.id)}>설명</button>
          </span>
        </div>)}
      </fieldset>)}
    </div> : <>
      <details className="term-graph-tools">
        <summary>그래프 조작</summary>
        <div className="term-graph-controls" role="group" aria-label="그래프 회전 조절">
        <button type="button" aria-label="왼쪽으로 회전" onClick={()=>rotate(-.2,0)}>↶</button>
        <button type="button" aria-label="오른쪽으로 회전" onClick={()=>rotate(.2,0)}>↷</button>
        <button type="button" aria-label="축소" disabled={view.zoom<=.65} onClick={()=>zoom(-.15)}>−</button>
        <span aria-live="off">{Math.round(view.zoom*100)}%</span>
        <button type="button" aria-label="확대" disabled={view.zoom>=1.6} onClick={()=>zoom(.15)}>+</button>
        <button type="button" onClick={()=>setView(INITIAL_VIEW)}>회전 초기화</button>
        </div>
      </details>
      <div ref={sceneRef} className="term-graph-scene" tabIndex={0} role="group" aria-label="회전 가능한 용어 공간"
        aria-describedby="term-graph-help" onKeyDown={key} onPointerDown={start} onPointerMove={move}
        onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
        data-yaw={view.yaw.toFixed(3)} data-pitch={view.pitch.toFixed(3)} data-zoom={view.zoom.toFixed(2)}>
        {graph.edges.some(edge=>edge.relation) && <div className="term-graph-relation-legend" aria-label="조건 연결선 안내">
          <span data-relation="all">실선: 모두 필요</span><span data-relation="any">점선: 하나 이상</span>
        </div>}
        <svg viewBox="0 0 1000 700" preserveAspectRatio="none" aria-hidden="true">
          {graph.edges.map(edge=><line key={`${edge.source}:${edge.target}:${edge.relation||'category'}`} x1={points[edge.source].x} y1={points[edge.source].y}
            x2={points[edge.target].x} y2={points[edge.target].y}
            style={{opacity:(points[edge.source].opacity+points[edge.target].opacity)/2*.55}}
            data-source={edge.source} data-target={edge.target} data-relation={edge.relation||'category'}
            className={focusedId===edge.target?'is-focused':''}/>)}
        </svg>
        {graph.nodes.map(node=>{
          const p=points[node.id];
          const style={left:`${p.x/10}%`,top:`${p.y/7}%`,zIndex:Math.round(p.depth+500),opacity:p.opacity,'--node-scale':p.scale};
          const expandLength=Math.hypot(p.x-500,p.y-350)||1;
          const expandStyle={...style,'--node-scale':Math.max(1,p.scale),
            '--expand-x':`${(p.x-500)/expandLength*42}px`,'--expand-y':`${(p.y-350)/expandLength*42}px`};
          return node.term ? <Fragment key={node.id}><button type="button" style={style} className="term-graph-node"
            data-focused={focusedId===node.id} data-selected={selectedIds.includes(node.id)}
            data-node-id={node.id} data-detail={Boolean(node.isDetail)} data-world-x={node.x.toFixed(3)} data-world-y={node.y.toFixed(3)}
            data-world-z={node.z.toFixed(3)} data-layout-x={p.x.toFixed(3)} data-layout-y={p.y.toFixed(3)}
            data-depth={p.depth.toFixed(3)} data-distant={p.depth < -40}
            aria-label={`${node.label} ${selectedIds.includes(node.id)?'선택 해제':'선택'}`} aria-pressed={selectedIds.includes(node.id)}
            onFocus={()=>{suppressClick.current=false;onFocus(node.id);}} onClick={()=>pick(node.id)}>
            <span className="term-graph-dot" aria-hidden="true">{selectedIds.includes(node.id)?'✓':''}</span>
            <span className="term-graph-label">{node.label}</span>
          </button>{node.expandable && <button type="button" className="term-graph-expand" style={expandStyle}
            data-node-id={`${node.id}:expand`} aria-label={`${node.label}: 이 조건이 필요한 세부 용어 ${expandedIds.includes(node.id)?'접기':'펼치기'}`}
            aria-expanded={expandedIds.includes(node.id)} onPointerDown={(event)=>event.stopPropagation()}
            onClick={(event)=>expand(event,node.id)}>{expandedIds.includes(node.id)?'−':'+'}</button>}</Fragment>
            : <span key={node.id} style={style} data-node-id={node.id} data-depth={p.depth.toFixed(3)} className="term-graph-category">{node.label}</span>;
        })}
      </div>
      <details className="term-graph-help-disclosure">
        <summary>조작 도움말</summary>
        <p id="term-graph-help" className="term-graph-help">노드 클릭으로 선택·해제 · 드래그로 회전 · 버튼/두 손가락으로 확대 · 공간에 초점을 두고 방향키로 회전 · Tab으로 용어 이동</p>
      </details>
    </>}
    <div className="term-graph-lower-overlay">
      {focused && <article className="term-graph-detail" aria-label="선택한 용어 설명">
      <div aria-live="polite"><h2>{focused.label_ko}</h2><p>{focused.plain_meaning_ko}</p></div>
      <div className="term-graph-actions">
        <button type="button" aria-pressed={selectedIds.includes(focused.term_id)} onClick={()=>onToggle(focused.term_id)}>{selectedIds.includes(focused.term_id)?'선택 해제':'용어 선택'}</button>
        <button type="button" disabled={focused.search_disabled} title={focused.search_disabled?'이 용어는 직접 검색할 수 없어요.':undefined}
          onClick={()=>onSearch(focused)}>레퍼런스 검색</button>
      </div>
      </article>}
      <footer className="term-graph-selection">
      {selected.length > 0 && <>
        <div className="term-graph-chips" aria-label="선택한 용어">
          {selected.map(term=><button key={term.term_id} type="button" aria-label={`${term.label_ko} 선택 해제`} onClick={()=>onToggle(term.term_id)}>{term.label_ko} <span aria-hidden="true">×</span></button>)}
        </div>
        <button type="button" onClick={()=>setNotice(onAdd(selected)?'선택한 용어를 입력에 추가했어요.':'500자 이내로 추가할 수 있도록 입력을 줄여 주세요.')}>선택 {selected.length}개 입력에 추가</button>
      </>}
      <p role="status">{notice}</p>
      </footer>
    </div>
  </section>;
}
