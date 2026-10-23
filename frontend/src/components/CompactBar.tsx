import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

import styles from "./CompactBar.module.css";

/** The height the shell's sticky header covers at the top of the window (--sticky-top). */
function stickyTop(): number {
  const value = getComputedStyle(document.documentElement).getPropertyValue("--sticky-top");
  return Number.parseFloat(value) || 0;
}

/** A ref callback for an element and whether that element has been scrolled out of view at the
 *  top of the window, under the shell's header. Without an IntersectionObserver (jsdom) it never
 *  has. */
export function useScrolledPast<T extends Element>(): [(element: T | null) => void, boolean] {
  const [element, setElement] = useState<T | null>(null);
  const [past, setPast] = useState(false);
  useEffect(() => {
    if (!element || typeof IntersectionObserver === "undefined") return;
    const top = stickyTop();
    const observer = new IntersectionObserver(
      ([entry]) => setPast(!entry.isIntersecting && entry.boundingClientRect.top < top),
      { rootMargin: `${-top}px 0px 0px 0px` },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, past];
}

/** The narrow bar below the shell's header while a detail page's header is scrolled out of view
 *  (D166), so the text, the HTML frame and the preview below get the height. Fixed, so showing
 *  it moves nothing on the page; 48 px high, which the frames and scroll margins below leave
 *  free together with the header's height. */
export function CompactBar({ label, children }: { label: string; children: ReactNode }) {
  const bar = useRef<HTMLDivElement>(null);
  const span = useSheetSpan(bar);
  return (
    <div
      ref={bar}
      role="region"
      aria-label={label}
      className={styles.bar}
      style={span ? { left: span.left, width: span.width } : undefined}
    >
      {children}
    </div>
  );
}

/** The white sheet a page stands on (D332): the outermost element around the bar that is
 *  narrower than the window, as the sheet beside the sidebar is; null when the page spans the
 *  window. */
function sheetOf(element: HTMLElement): HTMLElement | null {
  const windowWidth = document.documentElement.clientWidth;
  let sheet: HTMLElement | null = null;
  for (
    let node = element.parentElement;
    node && node !== document.body;
    node = node.parentElement
  ) {
    const { width } = node.getBoundingClientRect();
    if (width > 0 && width < windowWidth - 1) sheet = node;
  }
  return sheet;
}

/** Where the sheet stands across the window, followed as the window or the sidebar change its
 *  width; null without a sheet, where the bar spans the window. */
function useSheetSpan(
  element: RefObject<HTMLElement | null>,
): { left: number; width: number } | null {
  const [span, setSpan] = useState<{ left: number; width: number } | null>(null);
  useLayoutEffect(() => {
    if (!element.current) return;
    const bar = element.current;
    let observed: HTMLElement | null = null;
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => measure());
    function measure() {
      const sheet = sheetOf(bar);
      if (sheet !== observed) {
        if (observed) observer?.unobserve(observed);
        if (sheet) observer?.observe(sheet);
        observed = sheet;
      }
      const next = sheet ? sheet.getBoundingClientRect() : null;
      setSpan((now) =>
        next === null
          ? null
          : now?.left === next.left && now.width === next.width
            ? now
            : { left: next.left, width: next.width },
      );
    }
    measure();
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [element]);
  return span;
}
