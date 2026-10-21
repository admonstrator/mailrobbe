// The PDF viewer's script (D121), built on its own into /viewer/pdf.js (vite.viewer.config.ts).
// Its page's policy lets nothing load but this script: no Web Worker, no fetch, no stylesheet. So
// pdf.js parses on this thread with its worker code from this bundle (which it finds as
// globalThis.pdfjsWorker), the styles are injected, and the PDF comes from the app by postMessage.

import "pdfjs-dist/legacy/build/pdf.worker.mjs";

import { appMessage, type ViewerMessage } from "./protocol";
import css from "./viewer.css?inline";
import { PdfViewer } from "./viewer";

const style = document.createElement("style");
style.textContent = css;
document.head.append(style);

function element<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`the viewer's page has no #${id}`);
  return found as T;
}

/** To the app, whose origin is the one of this page's address: the sandbox makes only the
 *  document's own origin opaque. */
function post(message: ViewerMessage): void {
  window.parent.postMessage(message, location.origin);
}

function start(): void {
  const viewer = new PdfViewer({
    scroller: element("scroller"),
    pages: element("pages"),
    status: element("status"),
    pageNumber: element("page-number"),
    pageCount: element("page-count"),
    zoomOut: element("zoom-out"),
    zoomIn: element("zoom-in"),
    zoomValue: element("zoom-value"),
    fit: element("fit"),
  });
  let opened = false;
  window.addEventListener("message", (event) => {
    const message = appMessage(event, window.parent, location.origin);
    // One PDF per page: the app opens a new frame for another.
    if (!message || opened) return;
    opened = true;
    void viewer.open(message.data, message.name).then(post);
  });
  post({ type: "ready" });
}

document.addEventListener("DOMContentLoaded", start);
