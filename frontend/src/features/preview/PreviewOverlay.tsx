import { lazy, Suspense } from "react";

import type { PreviewKind } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { ImageViewer } from "./ImageViewer";
import { Overlay } from "./Overlay";
import styles from "./Overlay.module.css";

// The previews come in a chunk of their own when the first one opens: the mail detail is the
// screen used most, and most of its visits open none.
const AttachmentPreview = lazy(() =>
  import("./AttachmentPreview").then(({ AttachmentPreview }) => ({ default: AttachmentPreview })),
);

/** An attachment's preview over the page (D166), one at a time: images in the large view
 *  (D165), everything else as AttachmentPreview shows it (D120 to D123), filling the window.
 *  Closing unmounts it, which frees a PDF's memory and stops a player. */
export function PreviewOverlay({
  attachmentId,
  kind,
  name,
  onClose,
}: {
  attachmentId: number;
  kind: PreviewKind;
  name: string;
  onClose: () => void;
}) {
  if (kind === "image") {
    return <ImageViewer attachmentId={attachmentId} name={name} onClose={onClose} />;
  }
  return (
    <Overlay
      attachmentId={attachmentId}
      name={name}
      onClose={onClose}
      bodyClassName={styles.padded}
    >
      <Suspense
        fallback={
          <div className={styles.loading}>
            <Spinner label="Vorschau wird geladen" />
          </div>
        }
      >
        <AttachmentPreview attachmentId={attachmentId} kind={kind} name={name} fill />
      </Suspense>
    </Overlay>
  );
}
