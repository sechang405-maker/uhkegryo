export const GRAPH_CATEGORY_COLORS = Object.freeze({
  body:'#55C7E8',
  pose:'#FF9A62',
  composition:'#B69CFF',
  perspective:'#65D6A6',
  fallback:'#F2C75C',
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
  return isDetail?soften(categoryColor):categoryColor;
}
