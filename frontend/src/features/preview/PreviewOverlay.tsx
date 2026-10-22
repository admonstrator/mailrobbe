import { lazy, Suspense } from "react";

import type { PreviewKind } from "../../api/types";
import type { SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { ImageViewer } from "./ImageViewer";
import { Overlay } from "./Overlay";
import styles from "./Overlay.module.css";

// The previews come in a chunk of their own when the first one opens: the mail detail is the
// screen used most, and most of its visits open none.
const AttachmentPreview = lazy(() =>
  import("./AttachmentPreview").then(({ AttachmentPreview }) => ({ default: AttachmentPreview })),
);
const MediaWithTranscript = lazy(() =>
  import("./Transcript").then(({ MediaWithTranscript }) => ({ default: MediaWithTranscript })),
);

/** An attachment's preview over the page (D166), one at a time: images in the large view
 *  (D165), everything else as AttachmentPreview shows it (D120 to D123), filling the window, an
 *  opened PDF decrypted (D236). Audio and video whose document has a transcript show its lines
 *  below the player, the search words of marks marked (D296). Closing unmounts it, which frees a
 *  PDF's memory and stops a player. */
export function PreviewOverlay({
  attachmentId,
  kind,
  name,
  decrypted = false,
  transcriptOf = null,
  marks,
  onClose,
}: {
  attachmentId: number;
  kind: PreviewKind;
  name: string;
  decrypted?: boolean;
  /** The document whose transcript goes below the player. */
  transcriptOf?: number | null;
  marks?: SearchMarks;
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
        {(kind === "audio" || kind === "video") && transcriptOf !== null ? (
          <MediaWithTranscript
            attachmentId={attachmentId}
            kind={kind}
            name={name}
            documentId={transcriptOf}
            marks={marks}
          />
        ) : (
          <AttachmentPreview
            attachmentId={attachmentId}
            kind={kind}
            name={name}
            decrypted={decrypted}
            fill
          />
        )}
      </Suspense>
    </Overlay>
  );
}
