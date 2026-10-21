import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { attachmentContentUrl } from "../../api/client";
import { Button, buttonClass } from "../../components/Button";
import { cx } from "../../lib/cx";
import styles from "./Overlay.module.css";

/** An attachment over the page (D165, D166): a modal <dialog> filling the window but a margin,
 *  with a bar for the name, the download and Schließen, and the attachment below. Open while
 *  mounted; Esc, Schließen and a click on the backdrop call onClose, the parent unmounts it, and
 *  the focus goes back to where it was, the attachment's "Vorschau" as a rule. */
export function Overlay({
  attachmentId,
  name,
  tools,
  onClose,
  onKeyDown,
  bodyClassName,
  children,
}: {
  attachmentId: number;
  name: string;
  /** Controls of the content, in the bar before the download. */
  tools?: ReactNode;
  onClose: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDialogElement>) => void;
  bodyClassName?: string;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
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
      onKeyDown={onKeyDown}
      onClick={(event) => event.target === dialog.current && dialog.current.close()}
    >
      <div className={styles.bar}>
        <h2 id={titleId} className={styles.title} title={name}>
          {name}
        </h2>
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
      <div className={cx(styles.body, bodyClassName)}>{children}</div>
    </dialog>
  );
}
