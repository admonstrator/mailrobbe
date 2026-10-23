import { lazy, Suspense, useState, type ReactNode } from "react";

import type { PreviewKind } from "../../api/types";
import { Button } from "../../components/Button";
import type { SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { ImageViewer } from "./ImageViewer";
import { Overlay, type OverlayNav } from "./Overlay";
import styles from "./Overlay.module.css";

// The previews come in a chunk of their own when the first one opens: the mail detail is the
// screen used most, and most of its visits open none.
const AttachmentPreview = lazy(() =>
  import("./AttachmentPreview").then(({ AttachmentPreview }) => ({ default: AttachmentPreview })),
);
const MediaWithTranscript = lazy(() =>
  import("./Transcript").then(({ MediaWithTranscript }) => ({ default: MediaWithTranscript })),
);
const SocialDialog = lazy(() =>
  import("../social/SocialDialog").then(({ SocialDialog }) => ({ default: SocialDialog })),
);

/** An attachment's preview over the page (D166), one at a time: images in the large view
 *  (D165), everything else as AttachmentPreview shows it (D120 to D123), filling the window, an
 *  opened PDF decrypted (D236); without a kind, a note that the browser cannot show it (locked: it
 *  needs a password). Audio and video whose document has a transcript show its lines below the
 *  player, the search words of marks marked (D296), and "Als Bild teilen" makes a picture of a
 *  spoken transcript headed by this attachment's mail (D298). Beside it the aside, and the arrows
 *  of nav (D331). Closing unmounts it, which frees a PDF's memory and stops a player. */
export function PreviewOverlay({
  attachmentId,
  kind,
  name,
  locked = false,
  decrypted = false,
  transcriptOf = null,
  shareable = false,
  marks,
  nav,
  aside,
  onClose,
}: {
  attachmentId: number;
  kind: PreviewKind | null;
  name: string;
  locked?: boolean;
  decrypted?: boolean;
  /** The document whose transcript goes below the player. */
  transcriptOf?: number | null;
  /** Its transcript has words: offer the picture of it (D298). */
  shareable?: boolean;
  marks?: SearchMarks;
  nav?: OverlayNav;
  aside?: ReactNode;
  onClose: () => void;
}) {
  const [sharing, setSharing] = useState(false);
  if (kind === "image") {
    return (
      <ImageViewer
        attachmentId={attachmentId}
        name={name}
        nav={nav}
        aside={aside}
        onClose={onClose}
      />
    );
  }
  if (kind === null) {
    return (
      <Overlay
        attachmentId={attachmentId}
        name={name}
        nav={nav}
        aside={aside}
        onClose={onClose}
        bodyClassName={styles.padded}
      >
        <p className={styles.none}>
          {locked
            ? "Die Datei ist mit einem Kennwort geschützt; ohne Kennwort zeigt der Browser sie nicht."
            : "Diese Datei kann der Browser nicht zeigen. „Herunterladen“ öffnet sie in einem Programm deiner Wahl."}
        </p>
      </Overlay>
    );
  }
  const transcript = (kind === "audio" || kind === "video") && transcriptOf !== null;
  return (
    <Overlay
      attachmentId={attachmentId}
      name={name}
      nav={nav}
      aside={aside}
      onClose={onClose}
      bodyClassName={styles.padded}
      tools={
        transcript &&
        shareable && (
          <Button size="sm" onClick={() => setSharing(true)}>
            Als Bild teilen
          </Button>
        )
      }
    >
      <Suspense
        fallback={
          <div className={styles.loading}>
            <Spinner label="Vorschau wird geladen" />
          </div>
        }
      >
        {transcript && sharing && (
          <SocialDialog
            target={{ document: transcriptOf, attachment: attachmentId }}
            onClose={() => setSharing(false)}
          />
        )}
        {transcript ? (
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
