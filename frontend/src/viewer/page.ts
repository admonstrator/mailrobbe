// One page of the PDF viewer: a box of the page's size, its canvas while it is near the view, and
// a text layer for selecting, copying and the browser's search. No annotation layer: links, form
// fields and the PDF's scripts never reach the page (D121); annotations that have an appearance,
// such as stamps, are drawn into the canvas like the rest of the page.

import {
  TextLayer,
  type PDFDocumentProxy,
  type PDFPageProxy,
  type PageViewport,
  type RenderTask,
} from "pdfjs-dist/legacy/build/pdf.mjs";

import { outputScale } from "./scale";

/** CSS pixels per PDF point: at 100 % a page is as large as printed. */
const CSS_UNITS = 96 / 72;

/** A page's size at 100 %, in CSS pixels. */
export interface PageSize {
  width: number;
  height: number;
}

export function pageSize(page: PDFPageProxy): PageSize {
  const { width, height } = page.getViewport({ scale: CSS_UNITS });
  return { width, height };
}

export class PageView {
  readonly number: number;
  readonly div: HTMLDivElement;
  readonly #pdf: PDFDocumentProxy;
  #loading: Promise<PDFPageProxy> | null = null;
  #page: PDFPageProxy | null = null;
  #size: PageSize;
  #zoom: number;
  #canvas: HTMLCanvasElement | null = null;
  #drawnZoom = 0;
  #task: RenderTask | null = null;
  #text: TextLayer | null = null;

  /** size: the first page's, until this page is loaded. */
  constructor(pdf: PDFDocumentProxy, number: number, size: PageSize, zoom: number) {
    this.#pdf = pdf;
    this.number = number;
    this.#size = size;
    this.#zoom = zoom;
    this.div = document.createElement("div");
    this.div.className = "page";
    this.div.setAttribute("role", "region");
    this.div.setAttribute("aria-label", `Seite ${number}`);
    this.#layout();
  }

  /** Whether the canvas is missing or drawn at another zoom. */
  get stale(): boolean {
    return this.#drawnZoom !== this.#zoom;
  }

  /** Resizes the box at once; the canvas is stretched until it is drawn again. The text layer
   *  places its words in percent of the page and sizes them by --scale-factor. */
  setZoom(zoom: number): void {
    this.#zoom = zoom;
    this.#task?.cancel();
    this.#layout();
  }

  /** Draws the page at the current zoom into a new canvas, which replaces the old one once it is
   *  done, so zooming never shows an empty page. A page that cannot be drawn stays blank. */
  async draw(): Promise<void> {
    let zoom = this.#zoom;
    let canvas: HTMLCanvasElement | null = null;
    let task: RenderTask | null = null;
    try {
      const page = await this.#load();
      zoom = this.#zoom;
      const viewport = this.#viewport(page);
      const ratio = outputScale(viewport.width, viewport.height, window.devicePixelRatio);
      canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.floor(viewport.width * ratio));
      canvas.height = Math.max(1, Math.floor(viewport.height * ratio));
      const transform = [
        canvas.width / viewport.width,
        0,
        0,
        canvas.height / viewport.height,
        0,
        0,
      ];
      task = page.render({ canvas, viewport, transform });
      this.#task = task;
      await task.promise;
    } catch (error) {
      if (canvas) canvas.width = canvas.height = 0;
      if (error instanceof Error && error.name === "RenderingCancelledException") return;
      console.error(`page ${this.number}:`, error);
      this.#drawnZoom = zoom; // not drawn again and again
      return;
    } finally {
      if (task && this.#task === task) this.#task = null;
    }
    this.#dropCanvas();
    this.#canvas = canvas;
    this.#drawnZoom = zoom;
    this.div.prepend(canvas);
    await this.buildText();
  }

  /** Frees the canvas of a page far from the view; its text layer stays. */
  release(): void {
    this.#task?.cancel();
    this.#dropCanvas();
    this.#drawnZoom = 0;
    this.#page?.cleanup();
  }

  /** Builds the text layer once: invisible text over the canvas, at the place of the drawn
   *  text, so it can be selected, copied and found with Ctrl+F. */
  async buildText(): Promise<void> {
    if (this.#text) return;
    try {
      const page = await this.#load();
      if (this.#text) return;
      const container = document.createElement("div");
      container.className = "textLayer";
      this.#text = new TextLayer({
        textContentSource: page.streamTextContent(),
        container,
        viewport: this.#viewport(page),
      });
      this.div.append(container);
      await this.#text.render();
    } catch (error) {
      if (error instanceof Error && error.name === "AbortException") return;
      console.error(`text of page ${this.number}:`, error);
    }
  }

  destroy(): void {
    this.#task?.cancel();
    this.#text?.cancel();
    this.#dropCanvas();
  }

  /** The page itself, loaded once; from then on the box has the page's own size. */
  #load(): Promise<PDFPageProxy> {
    this.#loading ??= this.#pdf.getPage(this.number).then((page) => {
      this.#page = page;
      this.#size = pageSize(page);
      this.#layout();
      return page;
    });
    return this.#loading;
  }

  #viewport(page: PDFPageProxy): PageViewport {
    return page.getViewport({ scale: this.#zoom * CSS_UNITS });
  }

  /** The box's size, and the scale the text layer's CSS reads. */
  #layout(): void {
    const { style } = this.div;
    style.width = `${Math.floor(this.#size.width * this.#zoom)}px`;
    style.height = `${Math.floor(this.#size.height * this.#zoom)}px`;
    style.setProperty("--scale-factor", String(this.#zoom * CSS_UNITS));
    style.setProperty("--user-unit", String(this.#page?.userUnit ?? 1));
  }

  #dropCanvas(): void {
    if (!this.#canvas) return;
    this.#canvas.width = this.#canvas.height = 0; // frees its memory at once
    this.#canvas.remove();
    this.#canvas = null;
  }
}
