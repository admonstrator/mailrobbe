import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiSummaryView, AttachmentInfo } from "../../api/types";
import { aiSummaryNone, aiSummaryResult, mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { STRIP_MIN } from "./AttachmentsCard";

const [pdf, sheet] = mailDetail.attachments;
const PDF = "Rahmenvereinbarung_2026_final.pdf";
const SHEET = "Aenderungsprotokoll.xlsx";

/** The mail's summary, and the contract's with a hint (D331). */
const view: AiSummaryView = {
  ...aiSummaryNone,
  result: { ...aiSummaryResult, themes: [] },
  attachments: [
    {
      document_id: 5101,
      name: PDF,
      result: {
        ...aiSummaryResult,
        id: 503,
        target: "document",
        summary: "Der Vertrag regelt Lieferungen für 2026 und nennt Spenden ohne Quittungen.",
        tags: [{ id: 13, label: "Liefervertrag", mails: 6 }],
        themes: [
          {
            theme: "spenden",
            label: "Spendenaffären",
            quote: "Spenden ohne Quittungen",
            position: 40,
          },
        ],
        parts_read: 1,
        parts_total: 1,
      },
    },
  ],
};

function api(attachments: AttachmentInfo[] = mailDetail.attachments) {
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/mails/184221") return { ...mailDetail, attachments };
    if (path === "/api/ai/summary") return call.url.searchParams.has("mail") ? view : aiSummaryNone;
    return fixtureApi(call);
  };
}

async function attachmentsCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: /^Anhänge \(\d+\)$/ });
  return heading.closest("section")!;
}

const row = (card: HTMLElement, name: string) => within(card).getByText(name).closest("li")!;

describe("summaries in the attachment list (D331)", () => {
  it("show their beginning and hints in the row, the whole on request", async () => {
    renderApp("/mails/184221", api());
    const card = await attachmentsCard();
    await within(card).findByText("Hinweis: Spendenaffären");
    const contract = row(card, PDF);
    expect(within(contract).getByText("KI")).toBeTruthy();
    expect(within(contract).getByText(/^Der Vertrag regelt Lieferungen/)).toBeTruthy();
    fireEvent.click(
      within(contract).getByRole("button", { name: `Zusammenfassung von ${PDF} ganz zeigen` }),
    );
    expect(within(contract).getByText(/^Maschinell erzeugt/)).toBeTruthy();
    expect(within(contract).getByRole("link", { name: "Liefervertrag" })).toBeTruthy();
    expect(within(row(card, SHEET)).queryByText("KI")).toBeNull();
  });

  it("filter to the attachments with a hint or a summary", async () => {
    renderApp("/mails/184221", api());
    const card = await attachmentsCard();
    const filters = await within(card).findByRole("group", { name: "Anhänge zeigen" });
    expect(
      within(filters)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Alle 2", "Mit Hinweis 1", "Zusammengefasst 1"]);
    fireEvent.click(within(filters).getByRole("button", { name: "Mit Hinweis 1" }));
    expect(within(card).queryByText(SHEET)).toBeNull();
    expect(within(card).getByText(PDF)).toBeTruthy();
  });

  it("gather the attachments' tags and hints in the mail's card, a hint opening its attachment", async () => {
    renderApp("/mails/184221", api());
    const summary = await screen.findByRole("region", { name: "KI-Zusammenfassung" });
    const tags = within(summary).getByRole("list", { name: "Schlagwörter" });
    expect(within(tags).getByRole("link", { name: "Liefervertrag" })).toBeTruthy();
    expect(within(summary).getByText("Hinweis: Spendenaffären")).toBeTruthy();
    fireEvent.click(within(summary).getByRole("button", { name: PDF }));
    expect(screen.getByRole("dialog", { name: PDF })).toBeTruthy();
  });

  it("show many pictures as a strip that opens them", async () => {
    const pictures = Array.from({ length: STRIP_MIN }, (_, index) => ({
      ...sheet,
      id: 950 + index,
      document_id: 5200 + index,
      filename: `Foto_${index + 1}.jpg`,
      mime_type: "image/jpeg",
      kind: "image" as const,
      preview: "image" as const,
      pages: null,
    }));
    renderApp("/mails/184221", api([pdf, ...pictures]));
    const card = await attachmentsCard();
    const strip = await within(card).findByRole("list", { name: "Bilder" });
    expect(within(strip).getAllByRole("button")).toHaveLength(STRIP_MIN);
    expect(within(card).getByRole("heading", { name: `Bilder (${STRIP_MIN})` })).toBeTruthy();
    fireEvent.click(within(strip).getByRole("button", { name: "Foto_2.jpg" }));
    const viewer = screen.getByRole("dialog", { name: "Foto_2.jpg" });
    expect(within(viewer).getByRole("group", { name: "Zoom" })).toBeTruthy();
    expect(within(viewer).getByText("Anhang 3 von 4")).toBeTruthy();
  });
});

describe("an attachment over the page (D331)", () => {
  it("has its summary, sending and file beside it", async () => {
    renderApp("/mails/184221", api());
    const card = await attachmentsCard();
    fireEvent.click(within(row(card, PDF)).getByRole("button", { name: PDF }));
    const dialog = screen.getByRole("dialog", { name: PDF });
    const aside = within(dialog).getByRole("complementary", { name: "Zum Anhang" });
    expect(within(aside).getByText(/^Der Vertrag regelt Lieferungen/)).toBeTruthy();
    const fact = (label: string) => within(aside).getByText(label).nextElementSibling!.textContent;
    expect(fact("Von")).toBe("Anna Keller");
    expect(fact("Programm")).toBe("Microsoft Word für Microsoft 365");
    expect(fact("Autor")).toBe("Peter Hofmann");
    expect(fact("Seiten")).toBe("14");
    // the other mails of the archive carrying the document, from its page's figures
    expect(
      await within(aside).findByText(/^Im Archiv in 6 Mails, zuerst am 28\.09\.2026/),
    ).toBeTruthy();
    expect(
      within(aside).getByRole("link", { name: "Alle 6 Mails zeigen" }).getAttribute("href"),
    ).toMatch(/^\/mails\?.*document=5101/);
  });

  it("steps to the other attachments, by the buttons and the arrow keys", async () => {
    renderApp("/mails/184221", api());
    const card = await attachmentsCard();
    fireEvent.click(within(row(card, PDF)).getByRole("button", { name: PDF }));
    expect(within(screen.getByRole("dialog")).getByText("Anhang 1 von 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Nächster Anhang" }));
    const next = screen.getByRole("dialog", { name: SHEET });
    // no preview for a spreadsheet, but what the page knows about it
    expect(within(next).getByText(/Diese Datei kann der Browser nicht zeigen/)).toBeTruthy();
    expect(within(next).getByText("Noch keine Zusammenfassung.")).toBeTruthy();
    expect(
      within(next).getByText("Die Datei nennt weder Programm noch Autor noch Gerät."),
    ).toBeTruthy();
    fireEvent.keyDown(next, { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: PDF })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: SHEET })).toBeTruthy();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
