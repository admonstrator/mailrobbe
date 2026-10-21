import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AttachmentInfo } from "../../api/types";
import { mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

async function attachmentsCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: /^Anhänge \(\d+\)$/ });
  return heading.closest("section")!;
}

function item(card: HTMLElement, name: string): HTMLElement {
  return within(card).getByText(name).closest("li")!;
}

const withAttachments = (attachments: AttachmentInfo[]) => (call: ApiCall) =>
  call.url.pathname === "/api/mails/184221" ? { ...mailDetail, attachments } : fixtureApi(call);

describe("attachments of a mail", () => {
  it("download from the MBOX and lead to their documents", async () => {
    renderApp("/mails/184221");
    const card = await attachmentsCard();

    const pdf = item(card, "Rahmenvereinbarung_2026_final.pdf");
    expect(within(pdf).getByRole("img", { name: "PDF" })).toBeTruthy();
    const mime = within(pdf).getByTitle("application/pdf");
    expect(mime.parentElement!.textContent).toBe(
      "application/pdf · 14 Seiten · 168 KB · SHA-256 91ab…",
    );
    const download = within(pdf).getByRole("link", {
      name: "Rahmenvereinbarung_2026_final.pdf herunterladen",
    });
    expect(download.getAttribute("href")).toBe("/api/attachments/901/content");
    expect(download.hasAttribute("download")).toBe(true);
    // The document travels in six mails: this one and five others.
    expect(
      within(pdf).getByRole("link", { name: "auch in 5 weiteren Mails" }).getAttribute("href"),
    ).toBe("/anhaenge/5101");

    const sheet = item(card, "Aenderungsprotokoll.xlsx");
    expect(within(sheet).getByRole("img", { name: "Tabelle" })).toBeTruthy();
    expect(within(sheet).getByRole("link", { name: "Zum Dokument" }).getAttribute("href")).toBe(
      "/anhaenge/5102",
    );
    // Read as usual: no status label.
    expect(within(card).queryByText("Mit Text")).toBeNull();
  });

  it("show the text status where it says something and fall back to the MIME type", async () => {
    const [pdf, sheet] = mailDetail.attachments;
    renderApp(
      "/mails/184221",
      withAttachments([
        { ...pdf, text_status: "scanned", document_mails: 2 },
        // Imported before milestone 9 and not finalized yet: no document.
        {
          ...sheet,
          id: 903,
          filename: "Foto.jpg",
          mime_type: "image/jpeg",
          document_id: null,
          kind: null,
          text_status: null,
          pages: null,
          document_mails: null,
        },
      ]),
    );
    const card = await attachmentsCard();
    const scan = item(card, "Rahmenvereinbarung_2026_final.pdf");
    expect(within(scan).getByText("Gescannt")).toBeTruthy();
    expect(within(scan).getByRole("link", { name: "auch in 1 weiteren Mail" })).toBeTruthy();

    const photo = item(card, "Foto.jpg");
    expect(within(photo).getByRole("img", { name: "Bild" })).toBeTruthy();
    expect(within(photo).getByRole("link", { name: "Foto.jpg herunterladen" })).toBeTruthy();
    expect(within(photo).queryByRole("link", { name: /Dokument|weiteren/ })).toBeNull();
  });
});
