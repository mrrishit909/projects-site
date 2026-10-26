import { useEffect, useRef, useState } from "react";

/** Measured CSS width of an element, so SVG text keeps a constant pixel size at every breakpoint. */
export function useWidth<T extends HTMLElement>(initial = 640): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = (): void => setW(Math.max(240, Math.floor(el.getBoundingClientRect().width)));
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref as React.RefObject<T>, w];
}
