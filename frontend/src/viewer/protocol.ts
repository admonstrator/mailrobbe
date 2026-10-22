// The messages between the app and the PDF viewer (D121), for both sides. The viewer runs on an
// opaque origin and reaches nothing but its parent: it says it is ready, the app hands it the
// PDF's bytes (transferred, not copied), and the viewer answers how it went. Each side takes only
// messages from the other window and of a known shape.

/** Why the viewer could not show a PDF. */
export type FailReason = "encrypted" | "damaged" | "error";

/** From the viewer to the app. */
export type ViewerMessage =
  { type: "ready" } | { type: "loaded"; pages: number } | { type: "failed"; reason: FailReason };

/** From the app to the viewer: the PDF, whose buffer the app transfers. */
export interface PdfMessage {
  type: "pdf";
  data: ArrayBuffer;
  name: string;
}

/** What either side says when the viewer could not show a PDF. */
export const FAILURE_TEXTS: Record<FailReason, string> = {
  encrypted:
    "Dieses PDF ist mit einem Kennwort geschützt. Herunterladen und mit dem Kennwort öffnen.",
  damaged: "Das PDF ist beschädigt und lässt sich nicht anzeigen.",
  error: "Das PDF ließ sich nicht anzeigen. Herunterladen geht trotzdem.",
};

const REASONS: readonly unknown[] = ["encrypted", "damaged", "error"] satisfies FailReason[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The viewer's message in this event of the app's window; null when it comes from another
 *  window than the viewer's frame or is no message of the viewer. */
export function viewerMessage(
  event: MessageEvent,
  viewer: Window | null | undefined,
): ViewerMessage | null {
  if (!viewer || event.source !== viewer) return null;
  const data: unknown = event.data;
  if (!isRecord(data)) return null;
  if (data.type === "ready") return { type: "ready" };
  if (data.type === "loaded" && Number.isSafeInteger(data.pages) && Number(data.pages) >= 0) {
    return { type: "loaded", pages: Number(data.pages) };
  }
  if (data.type === "failed" && REASONS.includes(data.reason)) {
    return { type: "failed", reason: data.reason as FailReason };
  }
  return null;
}

/** The app's message in this event of the viewer's window; null when it does not come from the
 *  parent window on the app's origin (the origin of the viewer's own address, which the sandbox
 *  does not change) or is no PDF. */
export function appMessage(event: MessageEvent, parent: Window, origin: string): PdfMessage | null {
  if (event.source !== parent || event.origin !== origin) return null;
  const data: unknown = event.data;
  if (!isRecord(data) || data.type !== "pdf") return null;
  if (!(data.data instanceof ArrayBuffer) || typeof data.name !== "string") return null;
  return { type: "pdf", data: data.data, name: data.name };
}
