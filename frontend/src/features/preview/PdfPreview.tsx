import { useLayoutEffect, useRef, useState } from "react";

import {
  apiFetch,
  attachmentContentUrl,
  attachmentDecryptedUrl,
  PDF_VIEWER_URL,
} from "../../api/client";
import { cx } from "../../lib/cx";
import {
  FAILURE_TEXTS,
  viewerMessage,
  type FailReason,
  type PdfMessage,
} from "../../viewer/protocol";
import styles from "./AttachmentPreview.module.css";
import { IsolationNote, PreviewError } from "./PreviewParts";

/** How long the viewer may take to say it is ready once its page has loaded; without it, its
 *  script did not run (not built, or refused by the browser). */
export const VIEWER_START_TIMEOUT = 5000;

type PdfState =
  | { phase: "loading" }
  | { phase: "loaded"; pages: number }
  | { phase: "failed"; reason: FailReason }
  | { phase: "error"; error: Error }
  | { phase: "no-viewer" };

/** A PDF in the isolated viewer (D121): the app reads the bytes from the download endpoint (same
 *  origin, so Basic Auth applies) and hands them to the viewer's frame, which runs on an opaque
 *  origin without network and draws them with pdf.js. An opened PDF is read decrypted with the
 *  password found (D236). */
export function PdfPreview({
  attachmentId,
  name,
  fill,
  decrypted = false,
}: {
  attachmentId: number;
  name: string;
  fill?: boolean;
  decrypted?: boolean;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [state, setState] = useState<PdfState>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);

  // A layout effect: the listener is in place before the frame's first message can arrive.
  useLayoutEffect(() => {
    const element = frame.current;
    const controller = new AbortController();
    let bytes: ArrayBuffer | null = null;
    let ready = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    function send() {
      const viewer = element?.contentWindow;
      if (!bytes || !ready || !viewer) return;
      const message: PdfMessage = { type: "pdf", data: bytes, name };
      viewer.postMessage(message, "*", [bytes]); // an opaque origin has no name to address
      bytes = null;
    }
    function onMessage(event: MessageEvent) {
      const message = viewerMessage(event, element?.contentWindow);
      if (message?.type === "ready") {
        ready = true;
        clearTimeout(timer);
        send();
      } else if (message?.type === "loaded") {
        setState({ phase: "loaded", pages: message.pages });
      } else if (message?.type === "failed") {
        setState({ phase: "failed", reason: message.reason });
      }
    }
    function onLoad() {
      if (!ready) timer = setTimeout(() => setState({ phase: "no-viewer" }), VIEWER_START_TIMEOUT);
    }

    window.addEventListener("message", onMessage);
    element?.addEventListener("load", onLoad);
    const url = decrypted
      ? attachmentDecryptedUrl(attachmentId)
      : attachmentContentUrl(attachmentId);
    apiFetch(url, controller.signal)
      .then((answer) => answer.arrayBuffer())
      .then(
        (data) => {
          bytes = data;
          send();
        },
        (error: Error) => {
          if (!controller.signal.aborted) setState({ phase: "error", error });
        },
      );
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      element?.removeEventListener("load", onLoad);
    };
  }, [attachmentId, name, decrypted, attempt]);

  if (state.phase === "error") {
    return (
      <PreviewError
        error={state.error}
        onRetry={() => {
          setState({ phase: "loading" });
          setAttempt(attempt + 1);
        }}
      />
    );
  }
  if (state.phase === "failed" || state.phase === "no-viewer") {
    return (
      <p className={styles.message}>
        {state.phase === "failed"
          ? FAILURE_TEXTS[state.reason]
          : "Der PDF-Betrachter ließ sich nicht starten. Herunterladen geht trotzdem."}
      </p>
    );
  }
  return (
    <>
      <iframe
        ref={frame}
        className={cx(styles.frame, styles.pdf, fill && styles.fill)}
        title={`PDF-Vorschau von ${name}`}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        src={PDF_VIEWER_URL}
        aria-busy={state.phase === "loading"}
      />
      <IsolationNote />
    </>
  );
}
