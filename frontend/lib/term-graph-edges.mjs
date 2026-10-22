const CAMERA_DISTANCE=1100;
const EPSILON=1e-7;

export function perspectiveDepthAt(startDepth,endDepth,t,cameraDistance=CAMERA_DISTANCE) {
  if(t<=0) return startDepth;
  if(t>=1) return endDepth;
  const startInverse=1/(cameraDistance-startDepth);
  const endInverse=1/(cameraDistance-endDepth);
  return cameraDistance-1/((1-t)*startInverse+t*endInverse);
}

function screenParameterAtDepth(startDepth,endDepth,depth,cameraDistance) {
  const startInverse=1/(cameraDistance-startDepth);
  const endInverse=1/(cameraDistance-endDepth);
  const span=endInverse-startInverse;
  if(Math.abs(span)<Number.EPSILON) return null;
  return (1/(cameraDistance-depth)-startInverse)/span;
}

function uniqueSorted(values) {
  const sorted=[...values].sort((a,b)=>a-b);
  const unique=[];
  for(const value of sorted) {
    if(unique.length===0||Math.abs(value-unique[unique.length-1])>EPSILON) unique.push(value);
  }
  return unique;
}

function interpolate(start,end,t) { return start+(end-start)*t; }

/**
 * Split projected edges wherever their perspective-correct depth crosses a
 * visible node plane. Alternating z layers let HTML nodes and SVG edge pieces
 * participate in one painter order without flattening an entire edge to one z.
 */
function nodeRadius(node) {
  if(!node?.term) return 30;
  if(node.isDetail&&node.expandable) return 50;
  if(node.expandable) return 48;
  if(node.isDetail) return 42;
  return 40;
}

export function buildGraphDepthLayers(nodes,edges,points,{cameraDistance=CAMERA_DISTANCE,endpointTrim=null,viewport={width:1000,height:840}}={}) {
  const visibleNodes=nodes.filter(node=>!node.motionOrigin&&Number.isFinite(points[node.id]?.depth));
  const nodeById=new Map(visibleNodes.map(node=>[node.id,node]));
  const depths=uniqueSorted(visibleNodes.map(node=>points[node.id].depth));
  const nodeZ={};
  for(const node of visibleNodes) {
    const rank=depths.findIndex(depth=>Math.abs(depth-points[node.id].depth)<=EPSILON);
    nodeZ[node.id]=rank*2+2;
  }

  const layerMap=new Map();
  for(const edge of edges) {
    const start=points[edge.source],end=points[edge.target];
    if(!start||!end) continue;
    const screenLength=Math.hypot((end.x-start.x)*viewport.width/1000,(end.y-start.y)*viewport.height/840);
    const sourcePixels=endpointTrim===null?nodeRadius(nodeById.get(edge.source)):Math.max(0,endpointTrim);
    const targetPixels=endpointTrim===null?nodeRadius(nodeById.get(edge.target)):Math.max(0,endpointTrim);
    const sourceTrim=screenLength>EPSILON?Math.min(1,sourcePixels/screenLength):0;
    const targetTrim=screenLength>EPSILON?Math.min(1,targetPixels/screenLength):0;
    const cuts=[0,1];
    if(sourceTrim>EPSILON) cuts.push(sourceTrim);
    if(targetTrim>EPSILON) cuts.push(1-targetTrim);
    for(const depth of depths) {
      const t=screenParameterAtDepth(start.depth,end.depth,depth,cameraDistance);
      if(t!==null&&t>EPSILON&&t<1-EPSILON) cuts.push(t);
    }
    const ordered=uniqueSorted(cuts);
    for(let index=0;index<ordered.length-1;index+=1) {
      const t0=ordered[index],t1=ordered[index+1];
      if(t1-t0<=EPSILON) continue;
      const middle=(t0+t1)/2;
      const depth=perspectiveDepthAt(start.depth,end.depth,middle,cameraDistance);
      const belowCount=depths.filter(nodeDepth=>nodeDepth<depth-EPSILON).length;
      let zIndex=belowCount*2+1;
      let endpoint;
      const endpointMasks=[];
      if(sourceTrim>EPSILON&&t1<=sourceTrim+EPSILON) {
        endpointMasks.push('source');
        if(t0<EPSILON) endpoint='source';
        if(nodeZ[edge.source]!==undefined) zIndex=Math.min(zIndex,nodeZ[edge.source]-1);
      }
      if(targetTrim>EPSILON&&t0>=1-targetTrim-EPSILON) {
        endpointMasks.push('target');
        if(t1>1-EPSILON) endpoint='target';
        if(nodeZ[edge.target]!==undefined) zIndex=Math.min(zIndex,nodeZ[edge.target]-1);
      }
      const segment={
        ...edge,
        t0,t1,depth,endpoint,endpointMasks,segmentIndex:index,
        x1:interpolate(start.x,end.x,t0),
        y1:interpolate(start.y,end.y,t0),
        x2:interpolate(start.x,end.x,t1),
        y2:interpolate(start.y,end.y,t1),
        opacity:(start.opacity+end.opacity)/2*.55,
        dashOffset:screenLength*t0,
      };
      if(!layerMap.has(zIndex)) layerMap.set(zIndex,[]);
      layerMap.get(zIndex).push(segment);
    }
  }
  const layers=[...layerMap.entries()].sort(([a],[b])=>a-b).map(([zIndex,segments])=>({zIndex,segments}));
  return {nodeZ,layers};
}
