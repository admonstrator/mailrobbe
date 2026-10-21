import { useEffect, useState, type ReactNode } from "react";

import styles from "./CompactBar.module.css";

/** A ref callback for an element and whether that element has been scrolled out of view at the
 *  top of the window. Without an IntersectionObserver (jsdom) it never has. */
export function useScrolledPast<T extends Element>(): [(element: T | null) => void, boolean] {
  const [element, setElement] = useState<T | null>(null);
  const [past, setPast] = useState(false);
  useEffect(() => {
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) =>
      setPast(!entry.isIntersecting && entry.boundingClientRect.top < 0),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return [setElement, past];
}

/** The narrow bar at the top of the window while a detail page's header is scrolled out of view
 *  (D166), so the text, the HTML frame and the preview below get the height. Fixed, so showing
 *  it moves nothing on the page; 48 px high, which the frames and scroll margins below leave
 *  free. */
export function CompactBar({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} className={styles.bar}>
      {children}
    </div>
  );
}
