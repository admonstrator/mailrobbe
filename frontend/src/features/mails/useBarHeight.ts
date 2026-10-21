import { useEffect, useState } from "react";

/** A ref callback for a sticky bar above a table: its height, kept in the custom property
 *  --list-bar on its parent while it changes (chips wrap, the bulk bar comes and goes), so the
 *  table's head sticks right below it. Without a ResizeObserver (jsdom) the property stays unset
 *  and the head sticks below the shell header. */
export function useBarHeight<T extends HTMLElement>(): (element: T | null) => void {
  const [element, setElement] = useState<T | null>(null);
  useEffect(() => {
    const parent = element?.parentElement;
    if (!element || !parent || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      parent.style.setProperty("--list-bar", `${element.offsetHeight}px`),
    );
    observer.observe(element);
    return () => {
      observer.disconnect();
      parent.style.removeProperty("--list-bar");
    };
  }, [element]);
  return setElement;
}
