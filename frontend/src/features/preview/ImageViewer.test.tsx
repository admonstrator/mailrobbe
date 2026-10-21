import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { clampOffset, fitScale, ImageViewer, zoomOffset, zoomStep } from "./ImageViewer";

describe("zoom arithmetic of the large view", () => {
  it("fits the whole image, never above its own size", () => {
    expect(fitScale({ width: 3200, height: 2000 }, { width: 800, height: 500 })).toBe(0.25);
    expect(fitScale({ width: 1000, height: 4000 }, { width: 800, height: 500 })).toBe(0.125);
    expect(fitScale({ width: 320, height: 240 }, { width: 800, height: 500 })).toBe(1);
    // a strip of a thousand screens still shows as a sliver
    expect(fitScale({ width: 1_000_000, height: 10 }, { width: 800, height: 500 })).toBe(0.05);
  });

  it("steps through the zoom levels from wherever it stands", () => {
    expect(zoomStep(0.25, 1)).toBe(0.5);
    expect(zoomStep(0.25, -1)).toBe(0.1);
    expect(zoomStep(0.36, 1)).toBe(0.5);
    expect(zoomStep(0.36, -1)).toBe(0.25);
    expect(zoomStep(1, 1)).toBe(1.5);
    expect(zoomStep(8, 1)).toBe(8);
    expect(zoomStep(0.05, -1)).toBe(0.05);
  });

  it("keeps the point under the cursor in place", () => {
    // Twice the size around a point 100 px right of the centre: the image moves 100 px left.
    expect(zoomOffset({ x: 0, y: 0 }, { x: 100, y: 0 }, 1, 2)).toEqual({ x: -100, y: 0 });
    expect(zoomOffset({ x: -100, y: 40 }, { x: 0, y: 0 }, 2, 1)).toEqual({ x: -50, y: 20 });
  });

  it("lets no edge of a larger image come inside the window, and centres a smaller one", () => {
    const room = { width: 800, height: 500 };
    expect(clampOffset({ x: -5000, y: 300 }, { width: 3200, height: 2000 }, room)).toEqual({
      x: -1200,
      y: 300,
    });
    expect(clampOffset({ x: 40, y: -40 }, { width: 320, height: 240 }, room)).toEqual({
      x: 0,
      y: 0,
    });
  });
});

/** The large view of a 3200 x 2000 picture in a stage of 800 x 500, as a browser lays it out. */
function openLarge() {
  const onClose = vi.fn();
  render(<ImageViewer attachmentId={763} name="Plan.png" onClose={onClose} />);
  const dialog = screen.getByRole("dialog", { name: "Plan.png" });
  const image = within(dialog).getByRole("img", { name: "Großansicht von Plan.png" });
  const stage = image.parentElement!;
  Object.defineProperties(stage, { clientWidth: { value: 800 }, clientHeight: { value: 500 } });
  Object.defineProperties(image, { naturalWidth: { value: 3200 }, naturalHeight: { value: 2000 } });
  stage.setPointerCapture = vi.fn();
  fireEvent.load(image);
  const level = () => within(dialog).getByRole("group", { name: "Zoom" }).querySelector("span")!;
  return { dialog, image, stage, level, onClose };
}

describe("large view of an image", () => {
  it("opens fitted and zooms by key, by button and with Ctrl and the wheel", () => {
    const { dialog, image, stage, level } = openLarge();
    expect(image.getAttribute("src")).toBe("/api/attachments/763/content");
    expect(level().textContent).toBe("25 %");
    expect(image.style.width).toBe("800px");
    expect(image.style.transform).toBe("translate(-400px, -250px)");
    expect(
      within(dialog).getByRole("button", { name: "Einpassen" }).getAttribute("aria-pressed"),
    ).toBe("true");

    fireEvent.keyDown(dialog, { key: "+" });
    expect(level().textContent).toBe("50 %");
    fireEvent.keyDown(dialog, { key: "+" });
    expect(level().textContent).toBe("75 %");
    fireEvent.keyDown(dialog, { key: "-" });
    expect(level().textContent).toBe("50 %");
    fireEvent.click(within(dialog).getByRole("button", { name: "Verkleinern" }));
    expect(level().textContent).toBe("25 %");
    fireEvent.click(within(dialog).getByRole("button", { name: "Vergrößern" }));
    expect(level().textContent).toBe("50 %");

    fireEvent.click(within(dialog).getByRole("button", { name: "100 %" }));
    expect(level().textContent).toBe("100 %");
    expect(image.style.width).toBe("3200px");
    expect(stage.className).toMatch(/movable/);

    // A wheel without Ctrl moves the picture; with Ctrl it zooms.
    fireEvent.wheel(stage, { deltaX: 0, deltaY: 100 });
    expect(image.style.transform).toBe("translate(-1600px, -1100px)");
    fireEvent.wheel(stage, { ctrlKey: true, deltaY: 200 });
    expect(level().textContent).toBe("67 %");

    fireEvent.click(within(dialog).getByRole("button", { name: "Einpassen" }));
    expect(level().textContent).toBe("25 %");
    expect(image.style.transform).toBe("translate(-400px, -250px)");
    expect(stage.className).not.toMatch(/movable/);
  });

  it("drags a picture larger than the window, and a click beside it closes", () => {
    const { dialog, image, stage, onClose } = openLarge();
    fireEvent.click(within(dialog).getByRole("button", { name: "100 %" }));
    fireEvent.pointerDown(stage, { button: 0, clientX: 400, clientY: 250, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 300, clientY: 200, pointerId: 1 });
    fireEvent.pointerUp(stage, { pointerId: 1 });
    // the click ending the drag does not close
    fireEvent.click(stage);
    expect(onClose).not.toHaveBeenCalled();
    expect(image.style.transform).toBe("translate(-1700px, -1050px)");
    // no further than the picture's edge
    fireEvent.pointerDown(stage, { button: 0, clientX: 0, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: -5000, clientY: 0, pointerId: 1 });
    fireEvent.pointerUp(stage, { pointerId: 1 });
    expect(image.style.transform).toBe("translate(-2800px, -1050px)");

    fireEvent.click(image);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.pointerDown(stage, { button: 0, clientX: 10, clientY: 10, pointerId: 1 });
    fireEvent.pointerUp(stage, { pointerId: 1 });
    fireEvent.click(stage);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes by Schließen and offers the download", () => {
    const { dialog, onClose } = openLarge();
    expect(
      within(dialog).getByRole("link", { name: "Plan.png herunterladen" }).getAttribute("href"),
    ).toBe("/api/attachments/763/content");
    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("says so when the browser cannot show the picture", () => {
    render(<ImageViewer attachmentId={763} name="Scan.tif" onClose={() => {}} />);
    fireEvent.error(screen.getByRole("img", { name: "Großansicht von Scan.tif" }));
    expect(
      screen.getByText(
        "Der Browser kann dieses Bild nicht anzeigen. Herunterladen lässt es sich trotzdem.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Zoom" })).toBeNull();
    expect(screen.getByRole("link", { name: "Scan.tif herunterladen" })).toBeTruthy();
  });
});
