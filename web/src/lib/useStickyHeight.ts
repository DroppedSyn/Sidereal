import { useEffect, type RefObject } from 'react';

/** Keeps the CSS variable `name` on <html> equal to the element's rendered height, so other
 *  sticky elements and scroll offsets can sit below a sticky header whose height changes
 *  with the viewport (the top bar wraps on narrow screens). */
export function useStickyHeight(ref: RefObject<HTMLElement>, name = '--topbar-h'): void {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = document.documentElement;
    const update = () => root.style.setProperty(name, `${el.offsetHeight}px`);
    update();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => {
      ro.disconnect();
      root.style.removeProperty(name);
    };
  }, [ref, name]);
}
