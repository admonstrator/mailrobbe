import { describe, expect, it } from "vitest";

import { appMessage, viewerMessage } from "./protocol";

const app = "http://127.0.0.1:8000";

function event(data: unknown, source: Window | null, origin = "null"): MessageEvent {
  return new MessageEvent("message", { data, source, origin });
}

/** A window that is neither the app's nor the viewer's: a frame of its own. */
function otherWindow(): Window {
  const frame = document.createElement("iframe");
  document.body.append(frame);
  return frame.contentWindow!;
}

describe("messages of the PDF viewer, as the app reads them", () => {
  const viewer = otherWindow();

  it("takes the known messages from the viewer's frame", () => {
    expect(viewerMessage(event({ type: "ready" }, viewer), viewer)).toEqual({ type: "ready" });
    expect(viewerMessage(event({ type: "loaded", pages: 14 }, viewer), viewer)).toEqual({
      type: "loaded",
      pages: 14,
    });
    expect(viewerMessage(event({ type: "failed", reason: "encrypted" }, viewer), viewer)).toEqual({
      type: "failed",
      reason: "encrypted",
    });
  });

  it("ignores other windows", () => {
    expect(viewerMessage(event({ type: "ready" }, window), viewer)).toBeNull();
    expect(viewerMessage(event({ type: "ready" }, otherWindow()), viewer)).toBeNull();
    expect(viewerMessage(event({ type: "ready" }, null), viewer)).toBeNull();
    // No frame (yet): nothing is the viewer.
    expect(viewerMessage(event({ type: "ready" }, viewer), null)).toBeNull();
  });

  it("ignores other shapes", () => {
    for (const data of [
      null,
      "ready",
      { type: "pdf", data: new ArrayBuffer(4), name: "x.pdf" },
      { type: "loaded" },
      { type: "loaded", pages: "14" },
      { type: "loaded", pages: -1 },
      { type: "loaded", pages: 1.5 },
      { type: "failed", reason: "password" },
      { type: "failed" },
    ]) {
      expect(viewerMessage(event(data, viewer), viewer)).toBeNull();
    }
  });
});

describe("messages of the app, as the viewer reads them", () => {
  const parent = otherWindow();
  const data = new ArrayBuffer(8);

  it("takes the PDF from its parent on the app's origin", () => {
    expect(
      appMessage(event({ type: "pdf", data, name: "a.pdf" }, parent, app), parent, app),
    ).toEqual({ type: "pdf", data, name: "a.pdf" });
  });

  it("ignores other windows and origins", () => {
    const pdf = { type: "pdf", data, name: "a.pdf" };
    expect(appMessage(event(pdf, otherWindow(), app), parent, app)).toBeNull();
    expect(appMessage(event(pdf, parent, "http://evil.example"), parent, app)).toBeNull();
    expect(appMessage(event(pdf, parent, "null"), parent, app)).toBeNull();
  });

  it("ignores other shapes", () => {
    for (const message of [
      { type: "ready" },
      { type: "pdf", data: new Uint8Array(8), name: "a.pdf" },
      { type: "pdf", data: "%PDF-1.7", name: "a.pdf" },
      { type: "pdf", data },
      [data],
    ]) {
      expect(appMessage(event(message, parent, app), parent, app)).toBeNull();
    }
  });
});
