export function placeMasonry(width, heights, gap = 10, minWidth = 240) {
  const columns = Math.max(1, Math.floor((width + gap) / (minWidth + gap)));
  const itemWidth = Math.max(0, (width - gap * (columns - 1)) / columns);
  const bottoms = Array(columns).fill(0);
  const positions = heights.map(height => {
    const column = bottoms.indexOf(Math.min(...bottoms));
    const top = bottoms[column];
    bottoms[column] += Math.max(0, height) + gap;
    return { left: column * (itemWidth + gap), top };
  });
  return { itemWidth, positions, height: Math.max(0, ...bottoms) - (heights.length ? gap : 0) };
}
