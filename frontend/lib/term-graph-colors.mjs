export const GRAPH_CATEGORY_COLORS = Object.freeze({
  body:'#56C7D9',
  pose:'#F4A261',
  composition:'#B892FF',
  perspective:'#6FD3A3',
  fallback:'#F2C75C',
});

export const GRAPH_DETAIL_COLORS = Object.freeze({
  body:'#9CE4DA',
  pose:'#FFC28F',
  composition:'#D8C1FF',
  perspective:'#A9E58B',
});

export function graphCategoryColor(role) {
  return GRAPH_CATEGORY_COLORS[role]??GRAPH_CATEGORY_COLORS.fallback;
}

function soften(color, amount=0.18) {
  const channels=color.slice(1).match(/.{2}/g).map(channel=>Number.parseInt(channel,16));
  return `#${channels.map(channel=>Math.round(channel+(255-channel)*amount).toString(16).padStart(2,'0')).join('').toUpperCase()}`;
}

export function graphNodeColor(role,isDetail=false) {
  const categoryColor=graphCategoryColor(role);
  return isDetail?(GRAPH_DETAIL_COLORS[role]??soften(categoryColor)):categoryColor;
}
