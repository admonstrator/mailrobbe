import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentDetail } from "../../api/types";
import { aiStatus, documentSummary, ocrDocument, scannedDocument } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The fixture backend with the two scans and the AI endpoints a document page uses. */
function api(call: ApiCall): unknown {
  const path = call.url.pathname;
  const scans: DocumentDetail[] = [ocrDocument, scannedDocument];
  const scan = scans.find((document) => path === `/api/documents/${document.id}`);
  if (scan) return scan;
  if (path === `/api/documents/${ocrDocument.id}/text`) {
    return { text: "Vorstandssitzung 6. März\nQuittung", truncated: false, text_status: "text" };
  }
  if (path === "/api/ai/status") return aiStatus;
  if (path === "/api/ai/tasks")
    return { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "started" };
  if (path === "/api/ai/results/77/discard") return { changed: 1 };
  if (path === "/api/documents/summary") return { ...documentSummary, ocr_readable: 214 };
  return fixtureApi(call);
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);

describe("text recognition on a document", () => {
  it("marks a recognised text with engine, date and pages", async () => {
    renderApp(`/anhaenge/${ocrDocument.id}`, api);
    const card = await screen.findByRole("region", { name: "Erkannter Text" });
    expect(
      within(card).getByText(
        "Maschinell erkannt · Tesseract und qwen2.5vl:7b · 21.10.2026 · 2 von 3 Seiten",
      ),
    ).toBeTruthy();
    expect(within(card).getByText("Unsicher gelesen: Seite 2.")).toBeTruthy();
    expect(within(card).getByText(/Nicht gelesen: Seite 3\./)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Text anzeigen" }));
    expect(await within(card).findByText(/Vorstandssitzung/)).toBeTruthy();
  });

  it("recognises again at once with the chosen engine", async () => {
    const { calls } = renderApp(`/anhaenge/${ocrDocument.id}`, api);
    const card = await screen.findByRole("region", { name: "Erkannter Text" });
    fireEvent.click(within(card).getByRole("button", { name: "Neu erkennen" }));
    const dialog = await screen.findByRole("dialog", { name: "Text neu erkennen?" });
    // The engines come with the AI status; until then the button waits.
    const queue = within(dialog).getByRole("button", { name: "Jetzt erkennen" });
    await waitFor(() => expect(queue).toHaveProperty("disabled", false));
    fireEvent.click(queue);
    await waitFor(() => expect(posts(calls, "/api/ai/tasks")).toHaveLength(1));
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      document_ids: [ocrDocument.id],
      single: true,
      engine: "vision",
      start: true,
    });
  });

  it("discards a recognised text after a confirmation", async () => {
    const { calls } = renderApp(`/anhaenge/${ocrDocument.id}`, api);
    const card = await screen.findByRole("region", { name: "Erkannter Text" });
    fireEvent.click(within(card).getByRole("button", { name: "Verwerfen" }));
    const dialog = await screen.findByRole("dialog", { name: "Erkannten Text verwerfen?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Verwerfen" }));
    expect(await within(card).findByText("Der erkannte Text ist verworfen.")).toBeTruthy();
    expect(posts(calls, "/api/ai/results/77/discard")).toHaveLength(1);
  });

  it("starts the recognition of a scan without a text at once", async () => {
    const { calls } = renderApp(`/anhaenge/${scannedDocument.id}`, api);
    const card = await screen.findByRole("region", { name: "Texterkennung" });
    expect(within(card).queryByRole("button", { name: "Text anzeigen" })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Text erkennen" }));
    expect(await within(card).findByText(/Die Texterkennung läuft/)).toBeTruthy();
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      document_ids: [scannedDocument.id],
      single: true,
      engine: "auto",
      start: true,
    });
  });

  it("shows no text card for a document OCR cannot read", async () => {
    renderApp("/anhaenge/5105");
    await screen.findByRole("heading", { level: 1, name: "IMG_2041.jpg" });
    expect(screen.queryByRole("region", { name: "Texterkennung" })).toBeNull();
  });
});

describe("text source in the document list", () => {
  it("filters by text source and queues the filtered documents", async () => {
    const { calls } = renderApp("/anhaenge", api);
    const column = await screen.findByRole("complementary", { name: "Filter" });
    fireEvent.click(await within(column).findByRole("checkbox", { name: /Texterkennung/ }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/documents" &&
            call.url.searchParams.getAll("text_origin").join() === "ocr",
        ),
      ).toBe(true),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Für KI vormerken" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Für die Texterkennung vormerken?",
    });
    const queue = within(dialog).getByRole("button", { name: "214 Dokumente vormerken" });
    await waitFor(() => expect(queue).toHaveProperty("disabled", false));
    fireEvent.click(queue);
    expect(await within(dialog).findByText(/1 Dokument vorgemerkt/)).toBeTruthy();
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      filters: { text_origin: ["ocr"] },
      engine: "auto",
      include_logos: false,
    });
  });
});
