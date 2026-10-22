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

function clipAroundUnrelatedNodes(segment,visibleNodes,points,viewport) {
  const scaleX=viewport.width/1000,scaleY=viewport.height/840,
    start={x:segment.x1*scaleX,y:segment.y1*scaleY},end={x:segment.x2*scaleX,y:segment.y2*scaleY},
    dx=end.x-start.x,dy=end.y-start.y,lengthSquared=dx*dx+dy*dy,cuts=[0,1],obstacles=[];
  if(lengthSquared<=EPSILON) return [];
  for(const node of visibleNodes) {
    if(node.id===segment.source||node.id===segment.target) continue;
    const point=points[node.id];
    if(!point) continue;
    const obstacle={x:point.x*scaleX,y:point.y*scaleY,radius:nodeRadius(node)};
    obstacles.push(obstacle);
    const ox=start.x-obstacle.x,oy=start.y-obstacle.y,
      b=2*(ox*dx+oy*dy),c=ox*ox+oy*oy-obstacle.radius*obstacle.radius,
      discriminant=b*b-4*lengthSquared*c;
    if(discriminant<=0) continue;
    const root=Math.sqrt(discriminant);
    for(const value of [(-b-root)/(2*lengthSquared),(-b+root)/(2*lengthSquared)])
      if(value>EPSILON&&value<1-EPSILON) cuts.push(value);
  }
  const ordered=uniqueSorted(cuts),screenLength=Math.sqrt(lengthSquared),fragments=[];
  for(let index=0;index<ordered.length-1;index++) {
    const from=ordered[index],to=ordered[index+1],middle=(from+to)/2,
      x=start.x+dx*middle,y=start.y+dy*middle;
    if(obstacles.some(obstacle=>Math.hypot(x-obstacle.x,y-obstacle.y)<obstacle.radius-EPSILON)) continue;
    fragments.push({...segment,
      t0:interpolate(segment.t0,segment.t1,from),t1:interpolate(segment.t0,segment.t1,to),
      x1:interpolate(segment.x1,segment.x2,from),y1:interpolate(segment.y1,segment.y2,from),
      x2:interpolate(segment.x1,segment.x2,to),y2:interpolate(segment.y1,segment.y2,to),
      dashOffset:segment.dashOffset+screenLength*from,segmentIndex:`${segment.segmentIndex}-clip-${index}`});
  }
  return fragments;
}

export function buildGraphDepthLayers(nodes,edges,points,{cameraDistance=CAMERA_DISTANCE,endpointTrim=null,
  viewport={width:1000,height:840},edgeRoutes={}}={}) {
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
    const routeKey=`${edge.source}:${edge.target}:${edge.relation||'category'}`,
      path=[start,...(edgeRoutes[routeKey]||[]),end],legLengths=[];
    let screenLength=0;
    for(let leg=0;leg<path.length-1;leg++) {
      const length=Math.hypot((path[leg+1].x-path[leg].x)*viewport.width/1000,
        (path[leg+1].y-path[leg].y)*viewport.height/840);
      legLengths.push(length);screenLength+=length;
    }
    let travelled=0;
    for(let leg=0;leg<path.length-1;leg++) {
      const legStart=path[leg],legEnd=path[leg+1],legLength=legLengths[leg],firstLeg=leg===0,lastLeg=leg===path.length-2,
        sourcePixels=firstLeg?(endpointTrim===null?nodeRadius(nodeById.get(edge.source)):Math.max(0,endpointTrim)):0,
        targetPixels=lastLeg?(endpointTrim===null?nodeRadius(nodeById.get(edge.target)):Math.max(0,endpointTrim)):0,
        sourceTrim=legLength>EPSILON?Math.min(1,sourcePixels/legLength):0,
        targetTrim=legLength>EPSILON?Math.min(1,targetPixels/legLength):0,cuts=[0,1];
      if(sourceTrim>EPSILON) cuts.push(sourceTrim);
      if(targetTrim>EPSILON) cuts.push(1-targetTrim);
      for(const nodeDepth of depths) {
        const t=screenParameterAtDepth(legStart.depth,legEnd.depth,nodeDepth,cameraDistance);
        if(t!==null&&t>EPSILON&&t<1-EPSILON) cuts.push(t);
      }
      const ordered=uniqueSorted(cuts);
      for(let index=0;index<ordered.length-1;index+=1) {
        const localT0=ordered[index],localT1=ordered[index+1];
        if(localT1-localT0<=EPSILON) continue;
        const middle=(localT0+localT1)/2,depth=perspectiveDepthAt(legStart.depth,legEnd.depth,middle,cameraDistance),
          belowCount=depths.filter(nodeDepth=>nodeDepth<depth-EPSILON).length;
        let zIndex=belowCount*2+1,endpoint;
        const endpointMasks=[];
        if(firstLeg&&sourceTrim>EPSILON&&localT1<=sourceTrim+EPSILON) {
          endpointMasks.push('source');if(localT0<EPSILON) endpoint='source';
          if(nodeZ[edge.source]!==undefined) zIndex=Math.min(zIndex,nodeZ[edge.source]-1);
        }
        if(lastLeg&&targetTrim>EPSILON&&localT0>=1-targetTrim-EPSILON) {
          endpointMasks.push('target');if(localT1>1-EPSILON) endpoint='target';
          if(nodeZ[edge.target]!==undefined) zIndex=Math.min(zIndex,nodeZ[edge.target]-1);
        }
        const t0=screenLength>EPSILON?(travelled+legLength*localT0)/screenLength:0,
          t1=screenLength>EPSILON?(travelled+legLength*localT1)/screenLength:1,
          segment={...edge,t0,t1,depth,endpoint,endpointMasks,segmentIndex:`${leg}-${index}`,
            x1:interpolate(legStart.x,legEnd.x,localT0),y1:interpolate(legStart.y,legEnd.y,localT0),
            x2:interpolate(legStart.x,legEnd.x,localT1),y2:interpolate(legStart.y,legEnd.y,localT1),
            opacity:(legStart.opacity+legEnd.opacity)/2*.55,dashOffset:travelled+legLength*localT0};
        const visibleSegments=clipAroundUnrelatedNodes(segment,visibleNodes,points,viewport);
        if(!layerMap.has(zIndex)) layerMap.set(zIndex,[]);
        layerMap.get(zIndex).push(...visibleSegments);
      }
      travelled+=legLength;
    }
  }
  const layers=[...layerMap.entries()].sort(([a],[b])=>a-b).map(([zIndex,segments])=>({zIndex,segments}));
  return {nodeZ,layers};
}
