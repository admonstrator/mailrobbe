import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type PointerEvent,
} from "react";

import { attachmentContentUrl } from "../../api/client";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import styles from "./ImageViewer.module.css";
import { Overlay, type OverlayNav } from "./Overlay";

export interface Size {
  width: number;
  height: number;
}

export interface Point {
  x: number;
  y: number;
}

/** The zoom levels the buttons and keys step through; 1 is the image's own size. */
export const ZOOM_STEPS = [0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8] as const;
const MIN_ZOOM = ZOOM_STEPS[0];
const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

/** The scale that shows the whole image in room, never above its own size. */
export function fitScale(image: Size, room: Size): number {
  return clamp(Math.min(1, room.width / image.width, room.height / image.height), MIN_ZOOM, 1);
}

/** The next zoom step above (direction 1) or below (-1) scale, or scale at the ends. */
export function zoomStep(scale: number, direction: 1 | -1): number {
  const next =
    direction > 0
      ? ZOOM_STEPS.find((step) => step > scale * 1.001)
      : ZOOM_STEPS.findLast((step) => step < scale / 1.001);
  return next ?? clamp(scale, MIN_ZOOM, MAX_ZOOM);
}

/** The offset (of the image's centre from the room's) that keeps the point at, measured from
 *  the room's centre, on the same spot of the image when the scale goes from one to another. */
export function zoomOffset(offset: Point, at: Point, from: number, to: number): Point {
  const k = to / from;
  return { x: at.x - (at.x - offset.x) * k, y: at.y - (at.y - offset.y) * k };
}

/** The offset kept within what lets no edge of a drawn image larger than room come inside it;
 *  a smaller image stays in the middle. */
export function clampOffset(offset: Point, drawn: Size, room: Size): Point {
  const x = Math.max(0, (drawn.width - room.width) / 2);
  const y = Math.max(0, (drawn.height - room.height) / 2);
  return { x: clamp(offset.x, 0 - x, x), y: clamp(offset.y, 0 - y, y) }; // 0 - 0 is 0, not -0
}

function roomOf(element: HTMLElement | null): Size | null {
  return element ? { width: element.clientWidth, height: element.clientHeight } : null;
}

/** An image attachment in a large view over the page (D165): fitted to the window at first, zoom
 *  in steps, to 100 % and back, with the wheel while Ctrl or Cmd is held, dragging when it is
 *  larger than the window. It is the same <img> of the bytes served with their type as the
 *  preview (D76); nothing of the file runs. Esc, Schließen or a click beside the image close. */
export function ImageViewer({
  attachmentId,
  name,
  nav,
  aside,
  onClose,
}: {
  attachmentId: number;
  name: string;
  nav?: OverlayNav;
  aside?: ReactNode;
  onClose: () => void;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const [natural, setNatural] = useState<Size | null>(null);
  const [room, setRoom] = useState<Size | null>(null);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [offset, setOffset] = useState<Point>({ x: 0, y: 0 });
  const [broken, setBroken] = useState(false);
  // The latest press on the stage: a drag while it is down, and whether it moved, so that the
  // click ending a drag does not close the view.
  const drag = useRef<{ start: Point; from: Point; down: boolean; moved: boolean } | null>(null);

  const fit = natural && room ? fitScale(natural, room) : 1;
  const scale = zoom === "fit" ? fit : zoom;
  const drawn = natural && { width: natural.width * scale, height: natural.height * scale };
  const shift = drawn && room ? clampOffset(offset, drawn, room) : { x: 0, y: 0 };
  const movable = !!drawn && !!room && (drawn.width > room.width || drawn.height > room.height);

  function zoomTo(next: number | "fit", at: Point = { x: 0, y: 0 }) {
    if (!natural || !room) return;
    const to = next === "fit" ? fit : next;
    setOffset(next === "fit" ? { x: 0, y: 0 } : zoomOffset(shift, at, scale, to));
    setZoom(next === "fit" || Math.abs(to - fit) < 1e-9 ? "fit" : to);
  }

  const onWheel = useEffectEvent((event: WheelEvent) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey) {
      const box = stage.current!.getBoundingClientRect();
      const at = {
        x: event.clientX - box.left - box.width / 2,
        y: event.clientY - box.top - box.height / 2,
      };
      // A pinch on a trackpad comes as small steps with Ctrl held: zoom smoothly.
      zoomTo(clamp(scale * Math.exp(-event.deltaY * 0.002), MIN_ZOOM, MAX_ZOOM), at);
    } else if (movable) {
      setOffset({ x: shift.x - event.deltaX, y: shift.y - event.deltaY });
    }
  });

  useEffect(() => {
    const element = stage.current;
    const onResize = () => setRoom(roomOf(element));
    // Not React's onWheel: that listener is passive, and Ctrl with the wheel must not zoom the
    // page.
    const wheel = (event: WheelEvent) => onWheel(event);
    window.addEventListener("resize", onResize);
    element?.addEventListener("wheel", wheel, { passive: false });
    return () => {
      window.removeEventListener("resize", onResize);
      element?.removeEventListener("wheel", wheel);
    };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === "+" || event.key === "=") zoomTo(zoomStep(scale, 1));
    else if (event.key === "-") zoomTo(zoomStep(scale, -1));
    else return;
    event.preventDefault();
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const start = { x: event.clientX, y: event.clientY };
    drag.current = { start, from: shift, down: true, moved: false };
    if (movable) event.currentTarget.setPointerCapture(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const current = drag.current;
    if (!current?.down) return;
    const dx = event.clientX - current.start.x;
    const dy = event.clientY - current.start.y;
    if (Math.hypot(dx, dy) > 3) current.moved = true;
    if (movable && current.moved) setOffset({ x: current.from.x + dx, y: current.from.y + dy });
  }

  function release() {
    if (drag.current) drag.current.down = false;
  }

  return (
    <Overlay
      attachmentId={attachmentId}
      name={name}
      nav={nav}
      aside={aside}
      onClose={onClose}
      onKeyDown={onKeyDown}
      bodyClassName={styles.body}
      tools={
        !broken && (
          <div className={styles.tools} role="group" aria-label="Zoom">
            <Button
              size="sm"
              aria-label="Verkleinern"
              title="Verkleinern (Taste -)"
              disabled={!natural || scale <= MIN_ZOOM}
              onClick={() => zoomTo(zoomStep(scale, -1))}
            >
              −
            </Button>
            <span className={styles.level} aria-live="polite">
              {natural ? `${Math.round(scale * 100)} %` : "–"}
            </span>
            <Button
              size="sm"
              aria-label="Vergrößern"
              title="Vergrößern (Taste +)"
              disabled={!natural || scale >= MAX_ZOOM}
              onClick={() => zoomTo(zoomStep(scale, 1))}
            >
              +
            </Button>
            <Button
              size="sm"
              aria-pressed={zoom === 1}
              disabled={!natural}
              onClick={() => zoomTo(1)}
            >
              100 %
            </Button>
            <Button
              size="sm"
              aria-pressed={zoom === "fit"}
              disabled={!natural}
              onClick={() => zoomTo("fit")}
            >
              Einpassen
            </Button>
          </div>
        )
      }
    >
      <div
        ref={stage}
        className={cx(styles.stage, movable && styles.movable)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={release}
        onPointerCancel={release}
        onClick={(event) => {
          // Beside the image, and not the end of a drag.
          if (event.target === event.currentTarget && !drag.current?.moved) onClose();
        }}
      >
        {broken ? (
          <p className={styles.message}>
            Der Browser kann dieses Bild nicht anzeigen. Herunterladen lässt es sich trotzdem.
          </p>
        ) : (
          <>
            {!natural && (
              <div className={styles.loading}>
                <Spinner label="Bild wird geladen" />
              </div>
            )}
            <img
              src={attachmentContentUrl(attachmentId)}
              alt={`Großansicht von ${name}`}
              className={cx(styles.image, !natural && styles.pending)}
              draggable={false}
              style={
                drawn
                  ? {
                      width: drawn.width,
                      height: drawn.height,
                      transform: `translate(${shift.x - drawn.width / 2}px, ${shift.y - drawn.height / 2}px)`,
                    }
                  : undefined
              }
              onLoad={(event) => {
                const image = event.currentTarget;
                setNatural({ width: image.naturalWidth || 1, height: image.naturalHeight || 1 });
                setRoom(roomOf(stage.current));
              }}
              onError={() => setBroken(true)}
            />
          </>
        )}
      </div>
    </Overlay>
  );
}
