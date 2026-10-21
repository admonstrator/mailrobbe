import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DocumentDetail } from "../../api/types";
import { attachmentHtml, documentDetail, mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { VIEWER_START_TIMEOUT } from "./PdfPreview";

const NAME = "Rahmenvereinbarung_2026_final.pdf";

/** The document page of the contract PDF with this preview, and these answers of the API. */
function renderDocument(
  patch: Partial<DocumentDetail>,
  answers: Record<string, () => unknown> = {},
) {
  return renderApp("/anhaenge/5101", (call: ApiCall) => {
    if (call.url.pathname === "/api/documents/5101") return { ...documentDetail, ...patch };
    return answers[call.url.pathname]?.() ?? fixtureApi(call);
  });
}

const contractError = (status: number, code: string, message: string) => () =>
  Response.json({ detail: { code, message } }, { status });

function previewCard(): HTMLElement {
  return screen.getByRole("heading", { name: "Vorschau" }).closest("section")!;
}

/** A message from this window, as the app's window receives it. */
function postFrom(source: Window, data: unknown) {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, source, origin: "null" }));
  });
}

describe("PDF preview", () => {
  async function viewerFrame() {
    return (await screen.findByTitle(`PDF-Vorschau von ${NAME}`)) as HTMLIFrameElement;
  }

  it("opens the viewer isolated and hands it the PDF once it is ready", async () => {
    const { calls } = renderDocument({ preview: "pdf" });
    const frame = await viewerFrame();
    expect(frame.getAttribute("src")).toBe("/viewer/pdf.html");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(
      within(previewCard()).getByText("Isoliert angezeigt: ohne Skripte, ohne Netzzugriff."),
    ).toBeTruthy();
    await waitFor(() =>
      expect(calls.some((call) => call.url.pathname === "/api/attachments/901/content")).toBe(true),
    );

    const viewer = frame.contentWindow!;
    const post = vi.spyOn(viewer, "postMessage").mockImplementation(() => {});
    // Not from the viewer's frame, or not a message of the viewer: nothing happens.
    postFrom(window, { type: "ready" });
    postFrom(viewer, { type: "redy" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(post).not.toHaveBeenCalled();

    postFrom(viewer, { type: "ready" });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [message, target, transfer] = post.mock.calls[0] as unknown as [
      { type: string; data: ArrayBuffer; name: string },
      string,
      ArrayBuffer[],
    ];
    expect(message.type).toBe("pdf");
    expect(message.name).toBe(NAME);
    expect(new TextDecoder().decode(message.data).startsWith("%PDF-")).toBe(true);
    expect(target).toBe("*");
    expect(transfer).toEqual([message.data]);
    expect(frame.getAttribute("aria-busy")).toBe("true");

    postFrom(viewer, { type: "loaded", pages: 14 });
    expect(frame.getAttribute("aria-busy")).toBe("false");
  });

  it("says why the viewer could not show it", async () => {
    renderDocument({ preview: "pdf" });
    const frame = await viewerFrame();
    postFrom(frame.contentWindow!, { type: "failed", reason: "encrypted" });
    expect(
      screen.getByText(
        "Dieses PDF ist mit einem Passwort geschützt. Herunterladen und mit dem Passwort öffnen.",
      ),
    ).toBeTruthy();
    expect(screen.queryByTitle(`PDF-Vorschau von ${NAME}`)).toBeNull();
  });

  it("says when the MBOX file cannot be read, and tries again", async () => {
    let missing = true;
    renderDocument(
      { preview: "pdf" },
      {
        "/api/attachments/901/content": () =>
          missing ? contractError(409, "source_missing", "cannot read 2019.mbox")() : undefined,
      },
    );
    expect(await screen.findByText("Die MBOX-Datei ist nicht erreichbar.")).toBeTruthy();
    expect(screen.queryByTitle(`PDF-Vorschau von ${NAME}`)).toBeNull();
    missing = false;
    fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await viewerFrame()).toBeTruthy();
  });

  it("says when the viewer does not start", async () => {
    renderDocument({ preview: "pdf" });
    const frame = await viewerFrame();
    vi.useFakeTimers();
    try {
      fireEvent.load(frame);
      act(() => vi.advanceTimersByTime(VIEWER_START_TIMEOUT));
    } finally {
      vi.useRealTimers();
    }
    expect(
      screen.getByText("Der PDF-Betrachter ließ sich nicht starten. Herunterladen geht trotzdem."),
    ).toBeTruthy();
  });
});

describe("Word preview", () => {
  it("shows the converted HTML in a frame without scripts", async () => {
    renderDocument({ preview: "html", name: "Protokoll.docx", kind: "document" });
    const frame = await screen.findByTitle("Vorschau von Protokoll.docx");
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("srcdoc")).toBe(attachmentHtml);
    expect(screen.getByText("Isoliert angezeigt: ohne Skripte, ohne Netzzugriff.")).toBeTruthy();
  });

  it.each([
    [
      415,
      "no_preview",
      "Für diese Datei gibt es keine Vorschau im Browser. Herunterladen geht trotzdem.",
      "the first bytes are no DOCX",
      false,
    ],
    [
      413,
      "preview_too_large",
      "Die Datei ist zu groß für eine Vorschau. Herunterladen geht trotzdem.",
      null,
      false,
    ],
    [
      422,
      "preview_failed",
      "Die Vorschau ließ sich nicht erstellen. Herunterladen geht trotzdem.",
      "conversion ran out of time (60 s)",
      true,
    ],
    [
      409,
      "source_changed",
      "Die MBOX-Datei hat sich seit dem Import geändert; an dieser Stelle steht nicht mehr dieser Anhang.",
      null,
      false,
    ],
  ])("explains %i %s", async (status, code, title, reason, retry) => {
    renderDocument(
      { preview: "html", name: "Protokoll.docx" },
      { "/api/attachments/901/html": contractError(status, code, reason ?? "technical") },
    );
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(title)).toBeTruthy();
    if (reason) expect(within(alert).getByText(reason).tagName).toBe("CODE");
    else expect(within(alert).queryByText("technical")).toBeNull();
    expect(within(alert).queryByRole("button", { name: "Erneut versuchen" }) !== null).toBe(retry);
    expect(screen.queryByTitle("Vorschau von Protokoll.docx")).toBeNull();
  });
});

describe("preview over the mail", () => {
  it.each([
    ["pdf", "iframe"],
    ["html", "iframe"],
    ["video", "video"],
  ] as const)("fills the overlay with a %s preview", async (preview, tag) => {
    renderApp("/mails/184221", (call) =>
      call.url.pathname === "/api/mails/184221"
        ? {
            ...mailDetail,
            attachments: mailDetail.attachments.map((attachment) =>
              attachment.id === 901 ? { ...attachment, preview } : attachment,
            ),
          }
        : fixtureApi(call),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Vorschau" }));
    const dialog = screen.getByRole("dialog", { name: NAME });
    // the frame fills the overlay, unlike the document page's, which takes the window's height
    await waitFor(() => expect(dialog.querySelector(tag)?.className).toMatch(/fill/));
  });

  it("keeps the window's height on the document page", async () => {
    renderDocument({ preview: "pdf" });
    expect((await screen.findByTitle(`PDF-Vorschau von ${NAME}`)).className).not.toMatch(/fill/);
  });
});

describe("audio and video preview", () => {
  it("plays in the browser's player and says when it cannot", async () => {
    renderDocument({ preview: "video", name: "Messe.mp4", kind: "media" });
    const video = await screen.findByTitle("Messe.mp4");
    expect(video.tagName).toBe("VIDEO");
    expect(video.getAttribute("src")).toBe("/api/attachments/901/media");
    expect(video.hasAttribute("controls")).toBe(true);
    expect(video.getAttribute("preload")).toBe("metadata");
    fireEvent.error(video);
    expect(
      screen.getByText(
        "Der Browser kann diese Datei nicht abspielen. Herunterladen geht trotzdem.",
      ),
    ).toBeTruthy();
    expect(screen.queryByTitle("Messe.mp4")).toBeNull();
  });

  it("gives audio a player of its own", async () => {
    renderDocument({ preview: "audio", name: "Anruf.m4a", kind: "media" });
    const audio = await screen.findByTitle("Anruf.m4a");
    expect(audio.tagName).toBe("AUDIO");
    expect(audio.getAttribute("src")).toBe("/api/attachments/901/media");
  });
});
