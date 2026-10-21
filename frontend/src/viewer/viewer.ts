// The PDF viewer's document (D121): pages drawn lazily as they come near the view, text layers,
// page number and zoom. pdf.js gets the bytes and nothing else: no address to fetch from, no
// wasm (the policy forbids compiling it), no XFA, no scripting, no annotation layer.

import {
  getDocument,
  VerbosityLevel,
  type PDFDocumentProxy,
} from "pdfjs-dist/legacy/build/pdf.mjs";

import { pageSize, PageView, type PageSize } from "./page";
import { FAILURE_TEXTS, type FailReason, type ViewerMessage } from "./protocol";
import { fitWidth, MAX_ZOOM, MIN_ZOOM, stepZoom, zoomLabel } from "./scale";

/** Pages whose text layer is built ahead, in the background, so Ctrl+F finds their words before
 *  they were seen; further pages get theirs when they come near the view. */
const TEXT_AHEAD_PAGES = 200;
/** The scroller's padding around the pages, in CSS pixels (viewer.css). */
const PADDING = 12;

/** The page's elements the viewer works with (pdf.html). */
export interface ViewerElements {
  scroller: HTMLElement;
  pages: HTMLElement;
  status: HTMLElement;
  pageNumber: HTMLInputElement;
  pageCount: HTMLElement;
  zoomOut: HTMLButtonElement;
  zoomIn: HTMLButtonElement;
  zoomValue: HTMLOutputElement;
  fit: HTMLButtonElement;
}

/** encrypted for a password, damaged for a file pdf.js cannot read, else error. */
function failReason(error: unknown): FailReason {
  const name = error instanceof Error ? error.name : "";
  if (name === "PasswordException") return "encrypted";
  if (name === "InvalidPDFException") return "damaged";
  return "error";
}

function pause(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class PdfViewer {
  readonly #ui: ViewerElements;
  readonly #near: IntersectionObserver;
  #views: PageView[] = [];
  #viewOf = new Map<Element, PageView>();
  /** Pages within a screen's height of the view: drawn, and freed once they leave. */
  #nearViews = new Set<PageView>();
  #first: PageSize = { width: 0, height: 0 };
  #zoom = 1;
  #fit = true;
  #current = 1;
  #drawing = false;
  #scrollFrame = 0;

  constructor(ui: ViewerElements) {
    this.#ui = ui;
    this.#near = new IntersectionObserver((entries) => this.#onNear(entries), {
      root: ui.scroller,
      rootMargin: "100% 0px",
    });
    new ResizeObserver(() => {
      if (this.#fit) this.#setZoom(this.#fitZoom(), true);
    }).observe(ui.scroller);
    ui.scroller.addEventListener("scroll", () => this.#onScroll(), { passive: true });
    ui.pageNumber.addEventListener("change", () => this.#goTo(Number(ui.pageNumber.value)));
    ui.zoomOut.addEventListener("click", () => this.#setZoom(stepZoom(this.#zoom, -1), false));
    ui.zoomIn.addEventListener("click", () => this.#setZoom(stepZoom(this.#zoom, 1), false));
    ui.fit.addEventListener("click", () => this.#setZoom(this.#fitZoom(), true));
  }

  /** Opens the PDF and says how it went, for the app. */
  async open(data: ArrayBuffer, name: string): Promise<ViewerMessage> {
    document.title = name || "PDF";
    const task = getDocument({
      data: new Uint8Array(data),
      enableXfa: false,
      useWasm: false,
      verbosity: VerbosityLevel.ERRORS,
    });
    let pdf: PDFDocumentProxy;
    let first: PageSize;
    try {
      pdf = await task.promise;
      first = pageSize(await pdf.getPage(1));
    } catch (error) {
      const reason = failReason(error);
      console.warn(`PDF not shown: ${String(error)}`);
      this.#ui.status.textContent = FAILURE_TEXTS[reason];
      this.#ui.status.classList.add("failed");
      return { type: "failed", reason };
    }
    this.#show(pdf, first);
    return { type: "loaded", pages: pdf.numPages };
  }

  #show(pdf: PDFDocumentProxy, first: PageSize): void {
    const ui = this.#ui;
    this.#first = first;
    this.#zoom = this.#fitZoom();
    this.#views = Array.from(
      { length: pdf.numPages },
      (_, index) => new PageView(pdf, index + 1, first, this.#zoom),
    );
    ui.pages.replaceChildren(...this.#views.map((view) => view.div));
    for (const view of this.#views) {
      this.#viewOf.set(view.div, view);
      this.#near.observe(view.div);
    }
    ui.status.hidden = true;
    ui.pageCount.textContent = String(pdf.numPages);
    ui.pageNumber.max = String(pdf.numPages);
    ui.pageNumber.disabled = false;
    ui.fit.disabled = false;
    this.#showZoom();
    void this.#textAhead();
  }

  #onNear(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      const view = this.#viewOf.get(entry.target);
      if (!view) continue;
      if (entry.isIntersecting) this.#nearViews.add(view);
      else if (this.#nearViews.delete(view)) view.release();
    }
    void this.#drawNear();
  }

  /** Draws the near pages that need it, one at a time, the one closest to the current first. */
  async #drawNear(): Promise<void> {
    if (this.#drawing) return;
    this.#drawing = true;
    try {
      for (let view = this.#nextToDraw(); view; view = this.#nextToDraw()) {
        await view.draw();
        if (!this.#nearViews.has(view)) view.release(); // left the view while it was drawn
      }
    } finally {
      this.#drawing = false;
    }
  }

  #nextToDraw(): PageView | undefined {
    let next: PageView | undefined;
    for (const view of this.#nearViews) {
      const distance = Math.abs(view.number - this.#current);
      if (view.stale && (!next || distance < Math.abs(next.number - this.#current))) next = view;
    }
    return next;
  }

  /** The text layers of the first pages, built while no page is being drawn. */
  async #textAhead(): Promise<void> {
    for (const view of this.#views.slice(0, TEXT_AHEAD_PAGES)) {
      await pause(0);
      while (this.#drawing) await pause(100);
      await view.buildText();
    }
  }

  #onScroll(): void {
    if (this.#scrollFrame) return;
    this.#scrollFrame = requestAnimationFrame(() => {
      this.#scrollFrame = 0;
      const { scroller, pageNumber } = this.#ui;
      this.#current = this.#pageAt(scroller.scrollTop + scroller.clientHeight / 3);
      if (document.activeElement !== pageNumber) pageNumber.value = String(this.#current);
    });
  }

  /** The number of the page at this height of the scrolled content. */
  #pageAt(top: number): number {
    let low = 0;
    let high = this.#views.length - 1;
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (this.#views[middle].div.offsetTop <= top) low = middle;
      else high = middle - 1;
    }
    return low + 1;
  }

  #goTo(number: number): void {
    if (this.#views.length === 0) return;
    const page = Math.min(Math.max(Math.round(number) || 1, 1), this.#views.length);
    this.#ui.pageNumber.value = String(page);
    this.#ui.scroller.scrollTop = this.#views[page - 1].div.offsetTop - PADDING;
  }

  /** The zoom at which the first page fills the width ("Seitenbreite"). */
  #fitZoom(): number {
    return fitWidth(this.#ui.scroller.clientWidth - 2 * PADDING, this.#first.width);
  }

  /** Zooms all pages, keeping the place in the current page where it is. */
  #setZoom(zoom: number, fit: boolean): void {
    if (this.#views.length === 0) return; // nothing shown yet
    this.#fit = fit;
    if (zoom !== this.#zoom) {
      const { scroller } = this.#ui;
      const anchor = this.#views[this.#current - 1].div;
      const within = (scroller.scrollTop - anchor.offsetTop) / anchor.offsetHeight;
      this.#zoom = zoom;
      for (const view of this.#views) view.setZoom(zoom);
      scroller.scrollTop = anchor.offsetTop + within * anchor.offsetHeight;
      void this.#drawNear();
    }
    this.#showZoom();
  }

  #showZoom(): void {
    const ui = this.#ui;
    ui.zoomValue.value = zoomLabel(this.#zoom);
    ui.zoomOut.disabled = this.#zoom <= MIN_ZOOM;
    ui.zoomIn.disabled = this.#zoom >= MAX_ZOOM;
    ui.fit.setAttribute("aria-pressed", String(this.#fit));
  }
}
