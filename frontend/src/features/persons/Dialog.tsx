import { useEffect, useId, useRef, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Dialog.module.css";

/** A modal native <dialog>, open while mounted. Escape and a click on the backdrop call
 *  onClose; so do the content's own buttons, and the parent then unmounts it. */
export function Dialog({
  title,
  onClose,
  wide,
  children,
}: {
  title: ReactNode;
  onClose: () => void;
  /** Room for a picture beside its controls (the social media image, D217). */
  wide?: boolean;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      className={cx(styles.dialog, wide && styles.wide)}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => event.target === dialog.current && dialog.current.close()}
    >
      <div className={styles.body}>
        <h2 id={titleId} className={styles.title}>
          {title}
        </h2>
        {children}
      </div>
    </dialog>
  );
}
