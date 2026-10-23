import { useId, useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

import { attachmentContentUrl } from "../../api/client";
import { Button, buttonClass } from "../../components/Button";
import { cx } from "../../lib/cx";
import styles from "./Overlay.module.css";

/** Moving to the previous or next attachment of the mail while one is open (D331). */
export interface OverlayNav {
  position: string; // "Anhang 3 von 15"
  onPrev: () => void;
  onNext: () => void;
}

/** Whether a key goes to a field or a player, which use the arrows themselves. */
function ownsArrows(target: EventTarget): boolean {
  return (
    target instanceof Element &&
    target.closest("input, textarea, select, audio, video, [contenteditable]") !== null
  );
}

/** An attachment over the page (D165, D166): a modal <dialog> filling the window but a margin,
 *  with a bar for the name, the download and Schließen, and the attachment below; beside it what
 *  the page says about the attachment, and the arrows to the other attachments of the mail, also
 *  by the arrow keys (D331). Open while mounted, from its first paint; Esc, Schließen and a click
 *  on the backdrop call onClose, the parent unmounts it, and the focus goes back to where it was,
 *  the attachment's name as a rule. */
export function Overlay({
  attachmentId,
  name,
  tools,
  nav,
  aside,
  onClose,
  onKeyDown,
  bodyClassName,
  children,
}: {
  attachmentId: number;
  name: string;
  /** Controls of the content, in the bar before the download. */
  tools?: ReactNode;
  nav?: OverlayNav;
  /** The column beside the attachment. */
  aside?: ReactNode;
  onClose: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDialogElement>) => void;
  bodyClassName?: string;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  function keyDown(event: KeyboardEvent<HTMLDialogElement>) {
    onKeyDown?.(event);
    if (!nav || event.defaultPrevented || ownsArrows(event.target)) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (event.key === "ArrowLeft") nav.onPrev();
    else if (event.key === "ArrowRight") nav.onNext();
    else return;
    event.preventDefault();
  }

  // Before the first paint: the next attachment's dialog takes the place of the last one without
  // a frame of the page between them.
  useLayoutEffect(() => {
    const opener = document.activeElement;
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby={titleId}
      onClose={onClose}
      onKeyDown={keyDown}
      onClick={(event) => event.target === dialog.current && dialog.current.close()}
    >
      <div className={styles.bar}>
        <div className={styles.heading}>
          <h2 id={titleId} className={styles.title} title={name}>
            {name}
          </h2>
          {nav && <p className={styles.position}>{nav.position}</p>}
        </div>
        {nav && (
          <span className={styles.nav}>
            <Button
              size="sm"
              aria-label="Voriger Anhang"
              title="Voriger Anhang (Pfeil nach links)"
              onClick={nav.onPrev}
            >
              ‹
            </Button>
            <Button
              size="sm"
              aria-label="Nächster Anhang"
              title="Nächster Anhang (Pfeil nach rechts)"
              onClick={nav.onNext}
            >
              ›
            </Button>
          </span>
        )}
        {tools}
        <a
          href={attachmentContentUrl(attachmentId)}
          download
          className={buttonClass("default", "sm")}
          aria-label={`${name} herunterladen`}
        >
          Herunterladen
        </a>
        <Button size="sm" onClick={() => dialog.current?.close()}>
          Schließen
        </Button>
      </div>
      {aside ? (
        <div className={styles.split}>
          <div className={cx(styles.body, bodyClassName)}>{children}</div>
          <aside className={styles.aside} aria-label="Zum Anhang">
            {aside}
          </aside>
        </div>
      ) : (
        <div className={cx(styles.body, bodyClassName)}>{children}</div>
      )}
    </dialog>
  );
}
