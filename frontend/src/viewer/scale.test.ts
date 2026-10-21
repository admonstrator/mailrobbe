import { describe, expect, it } from "vitest";

import {
  fitWidth,
  MAX_CANVAS_PIXELS,
  MAX_CANVAS_SIDE,
  MAX_ZOOM,
  MIN_ZOOM,
  outputScale,
  stepZoom,
  zoomLabel,
} from "./scale";

describe("zoom of the PDF viewer", () => {
  it("steps to the next level, also from a fitted zoom between them", () => {
    expect(stepZoom(1, 1)).toBe(1.1);
    expect(stepZoom(1, -1)).toBe(0.9);
    expect(stepZoom(1.163, 1)).toBe(1.25);
    expect(stepZoom(1.163, -1)).toBe(1.1);
    expect(stepZoom(MAX_ZOOM, 1)).toBe(MAX_ZOOM);
    expect(stepZoom(MIN_ZOOM, -1)).toBe(MIN_ZOOM);
  });

  it("fits the page's width, within the limits", () => {
    expect(fitWidth(794, 794)).toBe(1);
    expect(fitWidth(1191, 794)).toBeCloseTo(1.5);
    expect(fitWidth(100, 10_000)).toBe(MIN_ZOOM);
    expect(fitWidth(10_000, 100)).toBe(MAX_ZOOM);
    expect(fitWidth(0, 794)).toBe(1);
  });

  it("says it in percent", () => {
    expect(zoomLabel(1.163)).toBe("116 %");
  });
});

describe("canvas of a page", () => {
  it("is as sharp as the screen", () => {
    expect(outputScale(794, 1123, 2)).toBe(2);
    expect(outputScale(794, 1123, 1)).toBe(1);
    expect(outputScale(794, 1123, 0.5)).toBe(1);
  });

  it("stays below the caps for a huge page or zoom", () => {
    const area = outputScale(3176, 4492, 2); // A4 at 400 % on a HiDPI screen
    expect(area).toBeLessThan(2);
    expect(3176 * 4492 * area * area).toBeLessThanOrEqual(MAX_CANVAS_PIXELS * 1.0001);
    const side = outputScale(20_000, 500, 2); // a long banner
    expect(20_000 * side).toBeLessThanOrEqual(MAX_CANVAS_SIDE);
  });
});
