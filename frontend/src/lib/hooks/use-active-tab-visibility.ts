"use client";

import { useCallback, useEffect, useState } from "react";

/** Keep the active item in a horizontal strip visible, without scrolling the page. */
export function useActiveTabVisibility(activeKey: string, selector = "[aria-current='page']") {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const ref = useCallback((node: HTMLElement | null) => { setElement(node); }, []);
  useEffect(() => {
    if (!element) return;
    const reveal = () => {
      const active = element.querySelector<HTMLElement>(selector);
      if (!active || !element.clientWidth) return;
      const item = active.getBoundingClientRect(), strip = element.getBoundingClientRect();
      if (item.left < strip.left) element.scrollLeft += item.left - strip.left;
      else if (item.right > strip.right) element.scrollLeft += item.right - strip.right;
    };
    const frame = requestAnimationFrame(reveal);
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(reveal) : null;
    observer?.observe(element);
    window.addEventListener("resize", reveal);
    return () => { cancelAnimationFrame(frame); observer?.disconnect(); window.removeEventListener("resize", reveal); };
  }, [element, activeKey, selector]);
  return ref;
}
