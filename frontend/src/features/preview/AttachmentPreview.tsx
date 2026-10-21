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
}

/** An attachment as the browser shows it (D120), by the kind the API decided (`preview` of an
 *  attachment or a document): nothing of it runs on the app's origin or reaches the network. */
export function AttachmentPreview({ kind, ...props }: PreviewProps & { kind: PreviewKind }) {
  switch (kind) {
    case "image":
      return <ImagePreview {...props} />;
    case "pdf":
      return <PdfPreview {...props} />;
    case "html":
      return <HtmlPreview {...props} />;
    case "audio":
    case "video":
      return <MediaPreview kind={kind} {...props} />;
  }
}

/** A raster image from the attachment's bytes (D76: served with its type only then); a damaged
 *  one says so instead of showing the browser's broken image. */
function ImagePreview({ attachmentId, name }: PreviewProps) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <p className={styles.message}>
        Der Browser kann dieses Bild nicht anzeigen. Herunterladen lässt es sich trotzdem.
      </p>
    );
  }
  return (
    <img
      src={attachmentContentUrl(attachmentId)}
      alt={`Vorschau von ${name}`}
      className={styles.image}
      onError={() => setBroken(true)}
    />
  );
}

/** A DOCX or ODT converted to HTML on the server (D122), in a frame without scripts. The HTML
 *  brings its own policy, which allows nothing from outside. */
function HtmlPreview({ attachmentId, name }: PreviewProps) {
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
        className={cx(styles.frame, styles.html)}
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
function MediaPreview({ attachmentId, name, kind }: PreviewProps & { kind: "audio" | "video" }) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <p className={styles.message}>
        Der Browser kann diese Datei nicht abspielen. Herunterladen geht trotzdem.
      </p>
    );
  }
  const player = {
    src: attachmentMediaUrl(attachmentId),
    title: name,
    controls: true,
    preload: "metadata",
    onError: () => setBroken(true),
  };
  return kind === "audio" ? (
    <audio className={styles.audio} {...player} />
  ) : (
    <video className={styles.video} playsInline {...player} />
  );
}
