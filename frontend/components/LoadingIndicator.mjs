"use client";

import { createElement as h, useEffect, useRef, useState } from "react";

export function LoadingIndicator({ label = "불러오는 중…", size = "medium" }) {
  return h("div", { className: "brand-loading", "data-size": size, role: "status" },
    h("span", { className: "brand-loading-dots", "aria-hidden": true },
      [0, 1, 2].map((index) => h("i", { key: index }))),
    h("span", null, label));
}

export function ImageSearchLoading({ label = "레퍼런스를 찾는 중입니다…" }) {
  return h("div", { className: "image-search-loading" },
    h(LoadingIndicator, { label, size: "large" }),
    h("div", { className: "pin-skeletons", "aria-hidden": true },
      Array.from({ length: 8 }, (_, index) => h("span", { className: "pin-skeleton", key: index }))));
}

export function LoadingImage({ size = "small", onError, onLoad, ...props }) {
  const [settled, setSettled] = useState(false);
  const imageRef = useRef(null);
  useEffect(() => {
    const image = imageRef.current;
    // Cached images may finish before hydration attaches the load handler.
    if (image?.complete) {
      setSettled(true);
      if (!image.naturalWidth) onError?.({ currentTarget: image, target: image });
    }
  }, []);
  return h("span", { className: "loading-image", "data-loading": !settled, "data-size": size },
    !settled && h(LoadingIndicator, { label: "이미지 불러오는 중…", size }),
    h("img", { ...props, ref: imageRef,
      onLoad: (event) => { setSettled(true); onLoad?.(event); },
      onError: (event) => { setSettled(true); onError?.(event); },
    }));
}
