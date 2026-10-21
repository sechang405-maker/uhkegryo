const DESIGN_WIDTH=1000;
const DESIGN_HEIGHT=840;

function nodeRadius(node) {
 if(node.isDetail) return node.expandable?48:40;
 return node.expandable?46:38;
}

export function assessGraphViewport(nodes,points,viewport) {
 const width=Number(viewport?.width)||0,height=Number(viewport?.height)||0;
 if(width<=0||height<=0) return {unsafe:false,reason:null,severeOverlapCount:0,clippedCount:0,minimumRatio:Infinity};
 const circles=nodes.filter(node=>node.term&&points[node.id]).map(node=>{
  const point=points[node.id],radius=nodeRadius(node);
  return {id:node.id,radius,x:point.x/DESIGN_WIDTH*width,y:point.y/DESIGN_HEIGHT*height};
 });
 let clippedCount=0,minimumRatio=Infinity,severeOverlapCount=0;
 for(const circle of circles) if(circle.x-circle.radius<0||circle.x+circle.radius>width||
   circle.y-circle.radius<0||circle.y+circle.radius>height) clippedCount++;
 for(let first=0;first<circles.length;first++) for(let second=first+1;second<circles.length;second++) {
  const a=circles[first],b=circles[second],ratio=Math.hypot(a.x-b.x,a.y-b.y)/(a.radius+b.radius);
  minimumRatio=Math.min(minimumRatio,ratio);
  if(ratio<.72) severeOverlapCount++;
 }
 const reason=clippedCount?'clipped':minimumRatio<.62?'critical-overlap':severeOverlapCount>=2?'overlap':null;
 return {unsafe:Boolean(reason),reason,severeOverlapCount,clippedCount,minimumRatio};
}
