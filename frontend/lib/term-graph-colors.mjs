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
