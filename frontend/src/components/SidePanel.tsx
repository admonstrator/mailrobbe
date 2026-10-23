import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";

import { cx } from "../lib/cx";
import { clampSize, setPanelLayout, usePanelLayout } from "../lib/panel";
import { CrossIcon, PanelBottomIcon, PanelRightIcon } from "./icons";
import styles from "./SidePanel.module.css";

const MIN_WIDTH = 320;
const MIN_HEIGHT = 160;
/** What stays of the list beside or above a panel at its largest. */
const LIST_ROOM_X = 360;
const LIST_ROOM_Y = 120;
const KEY_STEP = 32;

/** A panel beside a page's content (D334): a quick look without leaving the list, such as a
 *  mail's preview or the facets of a list. It sits beside the content, sticks below the header
 *  and scrolls on its own; Esc and the cross close it. `actions` stand left of the cross
 *  ("Ganz öffnen", "In neuem Fenster"). A `movable` panel (the previews, D337) stands at the
 *  right or along the bottom of the list, as chosen by its button and kept in this browser, and
 *  grows or shrinks by dragging its inner edge. */
export function SidePanel({
  label,
  title,
  actions,
  onClose,
  width,
  movable = false,
  className,
  children,
}: {
  /** The accessible name of the panel. */
  label: string;
  /** A visible heading in the panel's bar; without it only the actions stand there. */
  title?: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  /** CSS width, default --panel-width; a movable panel uses its stored width instead. */
  width?: string;
  movable?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("dialog, [role=dialog], [role=menu]")) return;
      close.current();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);

  const layout = usePanelLayout();
  const bottom = movable && layout.place === "bottom";
  const panel = useRef<HTMLElement>(null);
  // The size while dragging; stored once the drag ends, so the storage is written once.
  const [dragged, setDragged] = useState<number | null>(null);
  // Along the bottom the panel is fixed to the window, so it follows the list's left and right
  // edges (the sidebar folds) and leaves the list room to scroll its last rows above it.
  const [span, setSpan] = useState<{ left: number; width: number } | null>(null);

  const height = dragged ?? layout.height ?? Math.round(window.innerHeight * 0.45);
  const storedWidth = movable && layout.width !== null ? `${layout.width}px` : width;
  const currentWidth = dragged !== null ? `${dragged}px` : storedWidth;

  useLayoutEffect(() => {
    const parent = panel.current?.parentElement;
    if (!bottom || !parent) return;
    const measure = () => {
      const box = parent.getBoundingClientRect();
      setSpan({ left: box.left, width: box.width });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(parent);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [bottom]);

  useLayoutEffect(() => {
    const parent = panel.current?.parentElement;
    if (!bottom || !parent) return;
    parent.style.setProperty("padding-bottom", `${height}px`);
    // Rows reached by j and k scroll into view above the panel, not behind it.
    const root = document.documentElement;
    root.style.setProperty("scroll-padding-bottom", `${height}px`);
    return () => {
      parent.style.removeProperty("padding-bottom");
      root.style.removeProperty("scroll-padding-bottom");
    };
  }, [bottom, height]);

  const limits = (): [number, number] => {
    if (bottom) {
      return [MIN_HEIGHT, window.innerHeight - LIST_ROOM_Y - 56];
    }
    const room = panel.current?.parentElement?.getBoundingClientRect().width ?? window.innerWidth;
    return [MIN_WIDTH, room - LIST_ROOM_X];
  };

  const current = () =>
    bottom ? height : (panel.current?.getBoundingClientRect().width ?? MIN_WIDTH);

  const store = (value: number) => {
    setDragged(null);
    setPanelLayout(bottom ? { height: value } : { width: value });
  };

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const start = bottom ? event.clientY : event.clientX;
    const size = current();
    const [min, max] = limits();
    let value = size;
    const move = (e: PointerEvent) => {
      const delta = start - (bottom ? e.clientY : e.clientX);
      value = clampSize(size + delta, min, max);
      setDragged(value);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      store(value);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  };

  const keyResize = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const grow = bottom ? "ArrowUp" : "ArrowLeft";
    const shrink = bottom ? "ArrowDown" : "ArrowRight";
    if (event.key !== grow && event.key !== shrink) return;
    event.preventDefault();
    const [min, max] = limits();
    store(clampSize(current() + (event.key === grow ? KEY_STEP : -KEY_STEP), min, max));
  };

  const style: CSSProperties | undefined = bottom
    ? {
        height,
        left: span?.left ?? 0,
        width: span?.width ?? "100%",
        top: "auto",
        maxHeight: "none",
      }
    : currentWidth
      ? { width: currentWidth, flexBasis: currentWidth }
      : undefined;

  return (
    <aside
      ref={panel}
      aria-label={label}
      className={cx(styles.panel, bottom && styles.bottom, className)}
      style={style}
    >
      {movable && (
        <div
          role="separator"
          tabIndex={0}
          aria-orientation={bottom ? "horizontal" : "vertical"}
          aria-label={bottom ? "Höhe der Vorschau ändern" : "Breite der Vorschau ändern"}
          title="Ziehen ändert die Größe"
          className={styles.handle}
          onPointerDown={startDrag}
          onKeyDown={keyResize}
          onDoubleClick={() => setPanelLayout(bottom ? { height: null } : { width: null })}
        />
      )}
      <div className={styles.bar}>
        {title && <h2 className={styles.title}>{title}</h2>}
        <div className={styles.actions}>{actions}</div>
        {movable && (
          <button
            type="button"
            className={styles.close}
            aria-label={bottom ? "Vorschau rechts anzeigen" : "Vorschau unten anzeigen"}
            title={bottom ? "Vorschau rechts anzeigen" : "Vorschau unten anzeigen"}
            onClick={() => setPanelLayout({ place: bottom ? "right" : "bottom" })}
          >
            {bottom ? <PanelRightIcon size={18} /> : <PanelBottomIcon size={18} />}
          </button>
        )}
        <button
          type="button"
          className={styles.close}
          aria-label="Schließen"
          title="Schließen (Esc)"
          onClick={onClose}
        >
          <CrossIcon size={18} />
        </button>
      </div>
      <div className={styles.body} data-panel-body>
        {children}
      </div>
    </aside>
  );
}
