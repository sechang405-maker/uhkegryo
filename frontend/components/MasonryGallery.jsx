import { Children, useLayoutEffect, useRef } from "react";
import { placeMasonry } from "../lib/masonry.mjs";

export default function MasonryGallery({ children }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const root = ref.current;
    const items = [...root.children];
    let frame;
    function layout() {
      const width = root.clientWidth;
      if (!width) return;
      const { itemWidth } = placeMasonry(width, []);
      items.forEach(item => { item.style.width = `${itemWidth}px`; });
      const result = placeMasonry(width, items.map(item => item.getBoundingClientRect().height));
      items.forEach((item, index) => {
        const { left, top } = result.positions[index];
        item.style.transform = `translate(${left}px, ${top}px)`;
      });
      root.style.height = `${result.height}px`;
      root.dataset.masonry = "ready";
    }
    function schedule() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(layout);
    }
    const observer = new ResizeObserver(schedule);
    observer.observe(root);
    items.forEach(item => observer.observe(item));
    layout();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [children]);
  return <div className="pin-gallery-items" ref={ref}>
    {Children.toArray(children).map(child => <div className="masonry-item" key={child.key}>{child}</div>)}
  </div>;
}
