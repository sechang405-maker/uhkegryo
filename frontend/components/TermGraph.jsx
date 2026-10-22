'use client';

import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { buildExpandedTermGraph, INITIAL_VIEW, clamp, projectGraph, toggleExpanded } from '../lib/term-graph.mjs';
import { graphNodeColor } from '../lib/term-graph-colors.mjs';
import { buildGraphDepthLayers } from '../lib/term-graph-edges.mjs';
import { assessGraphViewport } from '../lib/term-graph-responsive.mjs';
import {
  createGraphMotionState,
  finishGraphMotion,
  interpolateGraphMotion,
  pauseGraphMotion,
  reconcileGraphMotion,
} from '../lib/term-graph-motion.mjs';
import { GRAPH_HELP_ITEMS } from '../lib/term-graph-help.mjs';

const GRAPH_MOTION_DURATION=180;

export default function TermGraph({terms, catalogTerms=terms, selectedIds, selectedSearchQuery, onToggle, onAdd, onSearch, focusedId, onFocus, list:listRequested, onListChange}) {
  const [motionState,setMotionState]=useState(()=>createGraphMotionState(buildExpandedTermGraph(terms,catalogTerms,[])));
  const [motionNow,setMotionNow]=useState(0);
  const [reducedMotion,setReducedMotion]=useState(false);
  const [pageVisible,setPageVisible]=useState(true);
  const motionStateRef=useRef(motionState);
  motionStateRef.current=motionState;
  const expandedIds=motionState.expandedIds;
  const logicalGraph=motionState.logicalGraph;
  const graph=motionState.displayGraph;
  const hasMotion=Object.keys(motionState.presence).length>0;
  const [view,setView]=useState(INITIAL_VIEW);
  const [notice,setNotice]=useState('');
  const [sceneSize,setSceneSize]=useState({width:1000,height:680});
  const [responsiveFallback,setResponsiveFallback]=useState(false);
  const responsivePoints=useMemo(()=>projectGraph(logicalGraph,INITIAL_VIEW),[logicalGraph]);
  const viewportAssessment=useMemo(()=>assessGraphViewport(logicalGraph.nodes,responsivePoints,sceneSize),
    [logicalGraph.nodes,responsivePoints,sceneSize]);
  const list=listRequested||logicalGraph.denseOverflow||responsiveFallback;
  const gesture=useRef(null);
  const rootRef=useRef(null);
  const sceneRef=useRef(null);
  const pointers=useRef(new Map());
  const suppressClick=useRef(false);
  const hiddenAt=useRef(null);
  const responsiveModeChecked=useRef(false);
  const onListChangeRef=useRef(onListChange);
  onListChangeRef.current=onListChange;
  const focused=catalogTerms.find(term=>term.term_id===focusedId);
  const selected=catalogTerms.filter(term=>selectedIds.includes(term.term_id));
  // An over-capacity fan has no honest non-overlapping 3D placement. Keep all
  // terms available through the existing list instead of rendering overlaps.
  const projection=useMemo(()=>interpolateGraphMotion(graph,motionState.presence,view,motionNow),
    [graph,motionState.presence,view,motionNow]);
  const points=projection.points;
  const colorByNodeId=useMemo(()=>new Map(graph.nodes.map(node=>[node.id,graphNodeColor(node.role,Boolean(node.isDetail))])),[graph.nodes]);
  const depthComposition=useMemo(()=>buildGraphDepthLayers(graph.nodes,graph.edges,points,{viewport:sceneSize}),
    [graph.nodes,graph.edges,points,sceneSize]);
  useEffect(()=>{
    setMotionState(current=>createGraphMotionState(
      buildExpandedTermGraph(terms,catalogTerms,current.expandedIds),current.expandedIds));
  },[terms,catalogTerms]);
  useEffect(()=>{
    if(list) return;
    const media=window.matchMedia('(prefers-reduced-motion: reduce)');
    const update=()=>{
      setReducedMotion(media.matches);
      if(media.matches) setMotionState(current=>createGraphMotionState(current.logicalGraph,current.expandedIds));
    };
    update();
    media.addEventListener?.('change',update);
    return ()=>media.removeEventListener?.('change',update);
  },[list]);
  useEffect(()=>{
    if(list) return;
    const update=()=>{
      const now=performance.now();
      if(document.hidden) {
        hiddenAt.current=now;
        setPageVisible(false);
        return;
      }
      if(hiddenAt.current!==null) {
        setMotionState(current=>pauseGraphMotion(current,now-hiddenAt.current));
        hiddenAt.current=null;
      }
      setMotionNow(now);
      setPageVisible(true);
    };
    update();
    document.addEventListener('visibilitychange',update);
    return ()=>document.removeEventListener('visibilitychange',update);
  },[list]);
  useEffect(()=>{
    if(!hasMotion||list||reducedMotion||!pageVisible) return;
    let frame=0;
    const tick=now=>{
      setMotionNow(now);
      setMotionState(current=>finishGraphMotion(current,now));
      frame=requestAnimationFrame(tick);
    };
    frame=requestAnimationFrame(tick);
    return ()=>cancelAnimationFrame(frame);
  },[hasMotion,list,reducedMotion,pageVisible]);
  useEffect(()=>{
    if(list) setMotionState(current=>createGraphMotionState(current.logicalGraph,current.expandedIds));
  },[list]);
  useEffect(()=>{
    // Responsive fallback is an initial presentation choice. Expanding a node
    // must never replace the graph the user is actively exploring.
    if(!listRequested&&!logicalGraph.denseOverflow&&expandedIds.length===0&&viewportAssessment.unsafe) setResponsiveFallback(true);
  },[listRequested,logicalGraph.denseOverflow,expandedIds.length,viewportAssessment.unsafe]);
  useEffect(()=>{
    if(responsiveModeChecked.current) return;
    responsiveModeChecked.current=true;
    if(window.matchMedia('(max-width: 760px)').matches&&!list) onListChangeRef.current(true);
  },[list]);
  useEffect(()=>{
    const scene=sceneRef.current;
    if(!scene) return;
    const handleWheel=(event)=>{
      event.preventDefault();
      const delta=clamp(-event.deltaY*.0015,-.12,.12);
      setView(current=>{
        const next={...current,zoom:clamp(current.zoom+delta,.65,1.25)};
        if(gesture.current) {
          gesture.current.view={...gesture.current.view,zoom:next.zoom};
          if(gesture.current.latest) gesture.current.latest={...gesture.current.latest,zoom:next.zoom};
        }
        return next;
      });
    };
    scene.addEventListener('wheel',handleWheel,{passive:false});
    return ()=>scene.removeEventListener('wheel',handleWheel);
  },[list]);
  useEffect(()=>{
    const scene=sceneRef.current,root=rootRef.current,target=scene||root;
    if(!target) return;
    const update=()=>{
      let {width,height}=target.getBoundingClientRect();
      if(!scene&&root) {
        const style=getComputedStyle(root);
        width-=parseFloat(style.paddingLeft)||0;width-=parseFloat(style.paddingRight)||0;
        height=window.matchMedia('(max-width: 760px)').matches?360:clamp(window.innerHeight*.6,480,680);
      }
      setSceneSize(current=>current.width===width&&current.height===height?current:{width,height});
    };
    update();
    const observer=new ResizeObserver(update);
    observer.observe(target);
    return ()=>observer.disconnect();
  },[list]);
  function rotate(dx,dy) { setView(v=>({...v,yaw:v.yaw+dx,pitch:clamp(v.pitch+dy,-1.2,1.2)})); }
  function zoom(delta) { setView(v=>({...v,zoom:clamp(v.zoom+delta,.65,1.25)})); }
  function start(event) {
    if(event.button!==0) return;
    if(event.target.closest?.('.term-graph-node')) return;
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
      g.latest={...g.view,zoom:clamp(g.view.zoom*distance/g.distance,.65,1.25)};
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
    const current=motionStateRef.current;
    const nextExpandedIds=toggleExpanded(current.expandedIds,id);
    const nextGraph=buildExpandedTermGraph(terms,catalogTerms,nextExpandedIds);
    const now=performance.now();
    setMotionNow(now);
    const nextState=reconcileGraphMotion(current,nextGraph,nextExpandedIds,id,now,GRAPH_MOTION_DURATION,list||reducedMotion);
    motionStateRef.current=nextState;
    setMotionState(nextState);
  }
  function key(event) {
    if(event.target!==event.currentTarget) return;
    const actions={ArrowLeft:()=>rotate(-.16,0),ArrowRight:()=>rotate(.16,0),ArrowUp:()=>rotate(0,-.16),ArrowDown:()=>rotate(0,.16),'+':()=>zoom(.1),'=':()=>zoom(.1),'-':()=>zoom(-.1),Home:()=>setView(INITIAL_VIEW)};
    if(actions[event.key]) {event.preventDefault();actions[event.key]();}
  }
  function toggleList() {
    suppressClick.current=false;
    if(list) {
      if(viewportAssessment.unsafe) return;
      if(responsiveFallback) setResponsiveFallback(false);
      else onListChange(false);
      return;
    }
    onListChange(true);
  }
  const listUnavailable=logicalGraph.denseOverflow||(list&&viewportAssessment.unsafe);
  const listTitle=logicalGraph.denseOverflow?'노드가 많아 읽기 쉬운 목록으로 표시합니다':
    list&&viewportAssessment.unsafe?'그래프 공간이 좁아 노드가 겹치는 동안 목록으로 표시합니다':undefined;
  return <section ref={rootRef} className="term-graph" aria-label="예시 용어 3D 그래프">
    <div className="term-graph-view-toggle">
      <button type="button" aria-pressed={list} disabled={listUnavailable}
        title={listTitle} onClick={toggleList}>{list?'3D 보기':'목록 보기'}</button>
    </div>
    {responsiveFallback&&<p className="term-graph-responsive-notice" role="status">
      {viewportAssessment.unsafe?'좁은 그래프 공간에서 노드가 겹치지 않도록 목록으로 표시합니다.':
        '패널을 넓힌 뒤 3D 보기를 선택하면 같은 선택과 펼침 상태로 돌아갑니다.'}
    </p>}
    {list ? <div className="term-graph-list" aria-label="전체 예시 용어 목록">
      {logicalGraph.nodes.filter(n=>!n.term).map(category=><fieldset key={category.id}><legend>{category.label}</legend>
        {logicalGraph.nodes.filter(n=>n.term && n.role===category.role).map(node=><div key={node.id}>
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
        <button type="button" aria-label="확대" disabled={view.zoom>=1.25} onClick={()=>zoom(.15)}>+</button>
        <button type="button" onClick={()=>setView(INITIAL_VIEW)}>회전 초기화</button>
        </div>
      </details>
      <div className="term-graph-scene" tabIndex={0} role="group" aria-label="회전 가능한 용어 공간"
        ref={sceneRef} aria-describedby="term-graph-help" onKeyDown={key} onPointerDown={start} onPointerMove={move}
        onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
        data-yaw={view.yaw.toFixed(3)} data-pitch={view.pitch.toFixed(3)} data-zoom={view.zoom.toFixed(2)}
        data-animating={hasMotion} data-page-visible={pageVisible}>
        {graph.edges.some(edge=>edge.relation) && <div className="term-graph-relation-legend" aria-label="조건 연결선 안내">
          <span data-relation="all">실선: 모두 필요</span><span data-relation="any">점선: 하나 이상</span>
        </div>}
        {depthComposition.layers.map(layer=><svg key={layer.zIndex} className="term-graph-edge-layer"
          style={{zIndex:layer.zIndex}} viewBox="0 0 1000 840" preserveAspectRatio="none" aria-hidden="true"
          data-edge-layer={layer.zIndex}>
          {layer.segments.map(segment=><line key={`${segment.source}:${segment.target}:${segment.relation||'category'}:${segment.segmentIndex}`}
            x1={segment.x1} y1={segment.y1} x2={segment.x2} y2={segment.y2}
            style={{opacity:segment.opacity,strokeDashoffset:segment.dashOffset,
              '--edge-color':colorByNodeId.get(segment.target)}}
            data-source={segment.source} data-target={segment.target} data-relation={segment.relation||'category'}
            data-segment-start={segment.t0.toFixed(7)} data-segment-end={segment.t1.toFixed(7)}
            data-segment-depth={segment.depth.toFixed(3)} data-endpoint={segment.endpoint||undefined}
            data-endpoint-mask={segment.endpointMasks.length?segment.endpointMasks.join(','):undefined}
            className={focusedId===segment.target?'is-focused':''}/>)}
        </svg>)}
        {graph.nodes.filter(node=>!node.motionOrigin).map(node=>{
          const p=points[node.id];
          const categoryColor=graphNodeColor(node.role,Boolean(node.isDetail));
          const motion=motionState.presence[node.id];
          const motionAmount=projection.amounts[node.id]??1;
          const exiting=motion?.target===0;
          const interactive=!motion;
          // A straight relationship edge and its child move from the same
          // parent. Scale the rendered child footprint by the same presence
          // amount so entering siblings do not cover each other's connectors.
          // Keep emerging siblings as a tiny seed while their safe paths fan
          // out from the same parent, then settle to full size near the fixed
          // destination, without changing any fixed world coordinate.
          const presenceScale=motion?Math.max(.001,motionAmount**10):1;
          const baseNodeScale=node.term?1:p.scale;
          const nodeScale=baseNodeScale*presenceScale;
          const style={left:`${p.x/10}%`,top:`${p.y/8.4}%`,zIndex:depthComposition.nodeZ[node.id],opacity:p.opacity,
            pointerEvents:node.term?(interactive?'auto':'none'):undefined,'--node-scale':nodeScale,'--motion-presence':motionAmount,
            '--category-color':categoryColor};
          const expandStyle={...style,'--node-scale':Math.max(1,baseNodeScale)*presenceScale,
            '--expand-x':'20px','--expand-y':'20px'};
          return node.term ? <Fragment key={node.id}><button type="button" style={style} className="term-graph-node"
            data-focused={focusedId===node.id} data-selected={selectedIds.includes(node.id)} data-expandable={node.expandable}
            data-category={node.role}
            data-node-id={node.id} data-detail={Boolean(node.isDetail)} data-world-x={node.x.toFixed(3)} data-world-y={node.y.toFixed(3)}
            data-world-z={node.z.toFixed(3)} data-layout-x={p.x.toFixed(3)} data-layout-y={p.y.toFixed(3)}
            data-depth={p.depth.toFixed(3)} data-distant={p.depth < -40}
            data-motion={motion?(exiting?'exit':'enter'):'idle'} data-motion-amount={motionAmount.toFixed(3)}
            aria-hidden={exiting||undefined} disabled={!interactive}
            aria-label={`${node.label} ${selectedIds.includes(node.id)?'선택 해제':'선택'}`} aria-pressed={selectedIds.includes(node.id)}
            onFocus={()=>{suppressClick.current=false;onFocus(node.id);}} onClick={()=>pick(node.id)}>
            <span className="term-graph-label">{node.label}</span>
          </button>{node.expandable && <button type="button" className="term-graph-expand" style={expandStyle}
            data-node-id={`${node.id}:expand`} aria-label={`${node.label}: 이 조건이 필요한 세부 용어 ${expandedIds.includes(node.id)?'접기':'펼치기'}`}
            aria-expanded={expandedIds.includes(node.id)} aria-hidden={exiting||undefined} disabled={!interactive}
            data-motion={motion?(exiting?'exit':'enter'):'idle'} data-motion-amount={motionAmount.toFixed(3)}
            onPointerDown={(event)=>event.stopPropagation()}
            onClick={(event)=>expand(event,node.id)}>{expandedIds.includes(node.id)?'−':'+'}</button>}</Fragment>
            : <span key={node.id} style={style} data-node-id={node.id} data-category={node.role} data-depth={p.depth.toFixed(3)} className="term-graph-category">{node.label}</span>;
        })}
      </div>
      <details className="term-graph-help-disclosure">
        <summary>조작 도움말</summary>
        <ul id="term-graph-help" className="term-graph-help">
          {GRAPH_HELP_ITEMS.map(item=><li key={item.label}><strong>{item.label}</strong><span>{item.description}</span></li>)}
        </ul>
      </details>
    </>}
    <div className="term-graph-lower-overlay">
      {focused && <article className="term-graph-detail" aria-label="선택한 용어 설명">
      <div aria-live="polite"><p className="term-graph-scope-label">현재 설명 중인 용어</p><h2>{focused.label_ko}</h2><p>{focused.plain_meaning_ko}</p></div>
      <div className="term-graph-actions">
        <button type="button" aria-pressed={selectedIds.includes(focused.term_id)} onClick={()=>onToggle(focused.term_id)}>{selectedIds.includes(focused.term_id)?'선택 해제':'용어 선택'}</button>
        <button type="button" disabled={focused.search_disabled} title={focused.search_disabled?'이 용어는 직접 검색할 수 없어요.':undefined}
          onClick={()=>onSearch(focused)}>현재 용어만 검색</button>
      </div>
      </article>}
      <footer className="term-graph-selection">
      <div className="term-graph-selection-summary">
        <strong>선택 조건 {selected.length}개</strong>
        <p>펼치기는 관련 용어를 보여 줄 뿐 선택 조건에 포함되지 않습니다.</p>
      </div>
      {selected.length > 0 ? <>
        <div className="term-graph-chips" aria-label="선택한 용어">
          {selected.map(term=><button key={term.term_id} type="button" aria-label={`${term.label_ko} 선택 해제`} onClick={()=>onToggle(term.term_id)}>{term.label_ko} <span aria-hidden="true">×</span></button>)}
        </div>
      </> : <p className="term-graph-selection-empty">검색에 포함할 조건을 노드에서 선택해 주세요.</p>}
      <div className="term-graph-selection-actions">
        {selected.length > 0 && <button type="button" onClick={()=>setNotice(onAdd(selected)?'선택한 용어를 입력에 추가했어요.':'500자 이내로 추가할 수 있도록 입력을 줄여 주세요.')}>선택 {selected.length}개 입력에 추가</button>}
        {selectedSearchQuery ? <a className="term-graph-search-all" href={`https://kr.pinterest.com/search/pins/?${new URLSearchParams({q:selectedSearchQuery})}`}
          target="_blank" rel="noopener noreferrer">선택 조건 전체 검색</a>
          : <button type="button" disabled={!selectedSearchQuery}>선택 조건 전체 검색</button>}
      </div>
      <p role="status">{notice}</p>
      </footer>
    </div>
  </section>;
}
