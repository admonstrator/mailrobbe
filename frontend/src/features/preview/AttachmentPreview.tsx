import { useState } from "react";

import { attachmentContentUrl, attachmentMediaUrl } from "../../api/client";
import { useAttachmentHtml } from "../../api/queries";
import type { PreviewKind } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import styles from "./AttachmentPreview.module.css";
import { PdfPreview } from "./PdfPreview";
import { IsolationNote, PreviewError } from "./PreviewParts";

interface PreviewProps {
  attachmentId: number;
  name: string;
  /** Frames fill the height of their container, the overlay, instead of the window's. */
  fill?: boolean;
}

/** An attachment as the browser shows it (D120), by the kind the API decided (`preview` of an
 *  attachment or a document): nothing of it runs on the app's origin or reaches the network.
 *  decrypted: it was opened with a found password (D236), so a PDF is read decrypted; the server
 *  decrypts a converted DOCX by itself, and a locked file has no preview. onMedia gets the
 *  player of audio and video, and null once it is gone, so a transcript can play it from a
 *  line's time (D296). */
export function AttachmentPreview({
  kind,
  decrypted = false,
  onMedia,
  ...props
}: PreviewProps & {
  kind: PreviewKind;
  decrypted?: boolean;
  onMedia?: (player: HTMLMediaElement | null) => void;
}) {
  switch (kind) {
    case "image":
      return <ImagePreview {...props} />;
    case "pdf":
      return <PdfPreview {...props} decrypted={decrypted} />;
    case "html":
      return <HtmlPreview {...props} />;
    case "audio":
    case "video":
      return <MediaPreview kind={kind} onMedia={onMedia} {...props} />;
  }
}

/** A raster image from the attachment's bytes (D76: served with its type only then); a damaged
 *  one says so instead of showing the browser's broken image. With onOpen, a click on it opens
 *  the large view (D165). */
export function ImagePreview({
  attachmentId,
  name,
  onOpen,
}: PreviewProps & { onOpen?: () => void }) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <p className={styles.message}>
        Der Browser kann dieses Bild nicht anzeigen. Herunterladen lässt es sich trotzdem.
      </p>
    );
  }
  const image = (
    <img
      src={attachmentContentUrl(attachmentId)}
      alt={`Vorschau von ${name}`}
      className={styles.image}
      onError={() => setBroken(true)}
    />
  );
  if (!onOpen) return image;
  return (
    <button type="button" className={styles.open} title="Großansicht" onClick={onOpen}>
      {image}
    </button>
  );
}

/** A DOCX or ODT converted to HTML on the server (D122), in a frame without scripts. The HTML
 *  brings its own policy, which allows nothing from outside. */
function HtmlPreview({ attachmentId, name, fill }: PreviewProps) {
  const html = useAttachmentHtml(attachmentId);
  if (html.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Vorschau wird erstellt" />
      </div>
    );
  }
  if (html.isError) return <PreviewError error={html.error} onRetry={() => void html.refetch()} />;
  return (
    <>
      <iframe
        className={cx(styles.frame, styles.html, fill && styles.fill)}
        title={`Vorschau von ${name}`}
        sandbox=""
        referrerPolicy="no-referrer"
        srcDoc={html.data}
      />
      <IsolationNote />
    </>
  );
}

/** Audio or video in the browser's own player (D123), which runs no code of the file. */
function MediaPreview({
  attachmentId,
  name,
  kind,
  fill,
  onMedia,
}: PreviewProps & {
  kind: "audio" | "video";
  onMedia?: (player: HTMLMediaElement | null) => void;
}) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <p className={styles.message}>
        Der Browser kann diese Datei nicht abspielen. Herunterladen geht trotzdem.
      </p>
    );
  }
  const player = {
    ref: onMedia,
    src: attachmentMediaUrl(attachmentId),
    title: name,
    controls: true,
    preload: "metadata",
    onError: () => setBroken(true),
  };
  return kind === "audio" ? (
    <audio className={styles.audio} {...player} />
  ) : (
    <video className={cx(styles.video, fill && styles.fill)} playsInline {...player} />
  );
}
