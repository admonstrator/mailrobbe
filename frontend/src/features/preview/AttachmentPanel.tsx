import { lazy, Suspense, useEffect, useSyncExternalStore } from "react";

import type { AttachmentInfo } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import styles from "./AttachmentPanel.module.css";

// The previews come in a chunk of their own when the first one opens: the mail detail is the
// screen used most, and most of its visits open none.
const AttachmentPreview = lazy(() =>
  import("./AttachmentPreview").then(({ AttachmentPreview }) => ({ default: AttachmentPreview })),
);

// The attachments of the mail detail open their previews one at a time, below the attachment.
// Which one is open lives here rather than in the card, so the card only places a toggle and a
// panel per attachment.
let openId: number | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setOpen(id: number | null): void {
  openId = id;
  for (const listener of listeners) listener();
}

function useOpen(id: number): boolean {
  return useSyncExternalStore(subscribe, () => openId === id);
}

const panelId = (id: number) => `anhang-vorschau-${id}`;

/** "Vorschau" for an attachment the browser can show (D120), else a muted "nur Download". */
export function PreviewToggle({ attachment }: { attachment: AttachmentInfo }) {
  const open = useOpen(attachment.id);
  if (!attachment.preview) return <span className={styles.downloadOnly}>nur Download</span>;
  return (
    <button
      type="button"
      className={styles.toggle}
      aria-expanded={open}
      aria-controls={panelId(attachment.id)}
      onClick={() => setOpen(open ? null : attachment.id)}
    >
      {open ? "Vorschau schließen" : "Vorschau"}
    </button>
  );
}

/** The open preview, at the card's full width below its attachment. Closing unmounts it, which
 *  frees a PDF's memory and stops a player. */
export function PreviewPanel({ attachment, name }: { attachment: AttachmentInfo; name: string }) {
  const open = useOpen(attachment.id);
  // Leaving the mail closes its preview, so coming back does not open it again.
  useEffect(
    () => () => {
      if (openId === attachment.id) setOpen(null);
    },
    [attachment.id],
  );
  if (!open || !attachment.preview) return null;
  return (
    <div
      id={panelId(attachment.id)}
      className={styles.panel}
      role="region"
      aria-label={`Vorschau von ${name}`}
    >
      <Suspense fallback={<Spinner label="Vorschau wird geladen" />}>
        <AttachmentPreview attachmentId={attachment.id} kind={attachment.preview} name={name} />
      </Suspense>
    </div>
  );
}
