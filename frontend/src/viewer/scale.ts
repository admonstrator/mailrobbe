// Zoom levels and canvas sizes of the PDF viewer: pure, so they can be tested without pdf.js.

/** The zoom steps of the buttons, as factors of the page's size at 100 %. */
export const ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 2, 2.5, 3, 4];
export const MIN_ZOOM = ZOOM_STEPS[0];
export const MAX_ZOOM = ZOOM_STEPS[ZOOM_STEPS.length - 1];

/** A page's canvas holds at most this many pixels (64 MiB at four bytes each) and this many in
 *  either direction: beyond, it is drawn at a lower resolution and stretched, so a huge page or
 *  a high zoom cannot take the browser's memory. */
export const MAX_CANVAS_PIXELS = 2 ** 24;
export const MAX_CANVAS_SIDE = 8192;

/** The next zoom step above (direction 1) or below (-1) zoom, within the limits. */
export function stepZoom(zoom: number, direction: 1 | -1): number {
  const next =
    direction > 0
      ? ZOOM_STEPS.find((step) => step > zoom + 0.001)
      : ZOOM_STEPS.findLast((step) => step < zoom - 0.001);
  return next ?? (direction > 0 ? MAX_ZOOM : MIN_ZOOM);
}

/** The zoom at which a page this wide at 100 % fills the available width, within the limits. */
export function fitWidth(available: number, pageWidth: number): number {
  if (available <= 0 || pageWidth <= 0) return 1;
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, available / pageWidth));
}

/** Canvas pixels per CSS pixel for a page drawn this large: the screen's pixel ratio, so it is
 *  sharp on HiDPI screens, unless the canvas would exceed the caps. */
export function outputScale(width: number, height: number, pixelRatio: number): number {
  const ratio = Math.max(1, pixelRatio);
  if (width <= 0 || height <= 0) return ratio;
  const byArea = Math.sqrt(MAX_CANVAS_PIXELS / (width * height));
  const bySide = MAX_CANVAS_SIDE / Math.max(width, height);
  return Math.min(ratio, byArea, bySide);
}

/** "125 %" */
export function zoomLabel(zoom: number): string {
  return `${Math.round(zoom * 100)} %`;
}
