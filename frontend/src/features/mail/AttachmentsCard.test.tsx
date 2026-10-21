import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AttachmentInfo } from "../../api/types";
import { mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { ATTACHMENTS_SHOWN } from "./AttachmentsCard";

async function attachmentsCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: /^Anhänge \(\d+\)$/ });
  return heading.closest("section")!;
}

function item(card: HTMLElement, name: string): HTMLElement {
  return within(card).getByText(name).closest("li")!;
}

const withAttachments = (attachments: AttachmentInfo[]) => (call: ApiCall) =>
  call.url.pathname === "/api/mails/184221" ? { ...mailDetail, attachments } : fixtureApi(call);

const [pdf, sheet] = mailDetail.attachments;
const photo: AttachmentInfo = {
  ...sheet,
  id: 903,
  filename: "IMG_0412.jpg",
  mime_type: "image/jpeg",
  kind: "image",
  text_status: "unsupported",
  pages: null,
  preview: "image",
  metadata: {
    author: null,
    modified_by: null,
    software: null,
    device: "Canon EOS 80D",
    created: null,
    gps: true,
  },
};

describe("attachments of a mail", () => {
  it("sit in the side column and download from the MBOX and lead to their documents", async () => {
    renderApp("/mails/184221");
    const card = await attachmentsCard();
    expect(card.closest("aside")).toBeTruthy();

    const contract = item(card, "Rahmenvereinbarung_2026_final.pdf");
    expect(within(contract).getByRole("img", { name: "PDF" })).toBeTruthy();
    const mime = within(contract).getByTitle("application/pdf");
    expect(mime.parentElement!.textContent).toBe(
      "application/pdf · 14 Seiten · 168 KB · SHA-256 91ab…",
    );
    // The whole name on hover, since a long one is cut after two lines.
    expect(within(contract).getByTitle("Rahmenvereinbarung_2026_final.pdf")).toBeTruthy();
    const download = within(contract).getByRole("link", {
      name: "Rahmenvereinbarung_2026_final.pdf herunterladen",
    });
    expect(download.getAttribute("href")).toBe("/api/attachments/901/content");
    expect(download.hasAttribute("download")).toBe(true);
    // The document travels in six mails: this one and five others.
    expect(
      within(contract).getByRole("link", { name: "auch in 5 weiteren Mails" }).getAttribute("href"),
    ).toBe("/anhaenge/5101");

    const spreadsheet = item(card, "Aenderungsprotokoll.xlsx");
    expect(within(spreadsheet).getByRole("img", { name: "Tabelle" })).toBeTruthy();
    expect(
      within(spreadsheet).getByRole("link", { name: "Zum Dokument" }).getAttribute("href"),
    ).toBe("/anhaenge/5102");
    // Read as usual: no status label.
    expect(within(card).queryByText("Mit Text")).toBeNull();
  });

  it("say what the file says about itself, and nothing without it", async () => {
    renderApp("/mails/184221", withAttachments([pdf, sheet, photo]));
    const card = await attachmentsCard();
    const contract = item(card, "Rahmenvereinbarung_2026_final.pdf");
    expect(within(contract).getByTitle("Was die Datei über sich sagt").textContent).toBe(
      "Autor Peter Hofmann · Microsoft Word für Microsoft 365 · 08.10.2026",
    );
    expect(
      within(item(card, "IMG_0412.jpg")).getByTitle("Was die Datei über sich sagt").textContent,
    ).toBe("Kamera Canon EOS 80D · mit Ortsangabe");
    expect(
      within(item(card, "Aenderungsprotokoll.xlsx")).queryByTitle("Was die Datei über sich sagt"),
    ).toBeNull();
  });

  it("show the text status where it says something and fall back to the MIME type", async () => {
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

    const foto = item(card, "Foto.jpg");
    expect(within(foto).getByRole("img", { name: "Bild" })).toBeTruthy();
    expect(within(foto).getByRole("link", { name: "Foto.jpg herunterladen" })).toBeTruthy();
    expect(within(foto).queryByRole("link", { name: /Dokument|weiteren/ })).toBeNull();
  });

  it("open a preview over the page, one at a time, and give the focus back on closing", async () => {
    renderApp(
      "/mails/184221",
      withAttachments([
        pdf,
        sheet,
        { ...pdf, id: 904, filename: "Anruf.m4a", mime_type: "audio/mp4", preview: "audio" },
      ]),
    );
    const card = await attachmentsCard();
    const contract = item(card, "Rahmenvereinbarung_2026_final.pdf");
    // The links keep their order; the preview comes after the download.
    expect(
      Array.from(contract.querySelectorAll("a, button"), (element) => element.textContent),
    ).toEqual(["Herunterladen", "Vorschau", "auch in 5 weiteren Mails"]);
    // The spreadsheet has none.
    const spreadsheet = item(card, "Aenderungsprotokoll.xlsx");
    expect(within(spreadsheet).getByText("nur Download")).toBeTruthy();
    expect(within(spreadsheet).queryByRole("button")).toBeNull();

    const open = within(contract).getByRole("button", { name: "Vorschau" });
    expect(open.getAttribute("aria-haspopup")).toBe("dialog");
    open.focus();
    fireEvent.click(open);
    const overlay = screen.getByRole("dialog", { name: "Rahmenvereinbarung_2026_final.pdf" });
    expect((overlay as HTMLDialogElement).open).toBe(true);
    expect(
      within(overlay)
        .getByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf herunterladen" })
        .getAttribute("href"),
    ).toBe("/api/attachments/901/content");
    // The previews come in a chunk of their own, loaded when the first one opens; the same
    // isolated viewer as on the document page.
    const frame = await within(overlay).findByTitle(
      "PDF-Vorschau von Rahmenvereinbarung_2026_final.pdf",
    );
    expect(frame.getAttribute("src")).toBe("/viewer/pdf.html");
    // Nothing below the attachment any more.
    expect(contract.querySelector("iframe")).toBeNull();

    fireEvent.click(within(overlay).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByTitle("PDF-Vorschau von Rahmenvereinbarung_2026_final.pdf")).toBeNull();
    expect(document.activeElement).toBe(open);

    fireEvent.click(within(item(card, "Anruf.m4a")).getByRole("button", { name: "Vorschau" }));
    const call = screen.getByRole("dialog", { name: "Anruf.m4a" });
    await waitFor(() =>
      expect(
        within(call)
          .getAllByTitle("Anruf.m4a")
          .map((element) => element.tagName),
      ).toEqual(["H2", "AUDIO"]),
    );
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("open an image in the large view", async () => {
    renderApp("/mails/184221", withAttachments([pdf, photo]));
    const card = await attachmentsCard();
    fireEvent.click(within(item(card, "IMG_0412.jpg")).getByRole("button", { name: "Vorschau" }));
    const viewer = screen.getByRole("dialog", { name: "IMG_0412.jpg" });
    expect(within(viewer).getByRole("img", { name: "Großansicht von IMG_0412.jpg" })).toBeTruthy();
    expect(within(viewer).getByRole("group", { name: "Zoom" })).toBeTruthy();
  });

  it("show the first eight of many and the rest on request, search hits always", async () => {
    const many = Array.from({ length: 40 }, (_, index): AttachmentInfo => ({
      ...sheet,
      id: 1000 + index,
      filename: `Beleg_${index}.pdf`,
    }));
    renderApp(`/mails/184221?${new URLSearchParams({ q: "Haftung" })}`, (call) => {
      if (call.url.pathname === "/api/mails/184221") return { ...mailDetail, attachments: many };
      if (call.url.pathname === "/api/mails/184221/hits") {
        return {
          words: ["haftung"],
          stems: [],
          in_mail: false,
          attachments: [{ attachment_id: 1030, in_name: false, snippet: "die Haftung" }],
        };
      }
      return fixtureApi(call);
    });
    const card = await attachmentsCard();
    expect(within(card).getByRole("heading").textContent).toBe("Anhänge (40)");
    await within(card).findByText("Beleg_30.pdf");
    expect(within(card).getAllByRole("listitem")).toHaveLength(ATTACHMENTS_SHOWN + 1);
    expect(within(card).queryByText("Beleg_8.pdf")).toBeNull();

    fireEvent.click(within(card).getByRole("button", { name: "alle 40 anzeigen" }));
    expect(within(card).getAllByRole("listitem")).toHaveLength(40);
    expect(within(card).queryByRole("button", { name: /^alle/ })).toBeNull();
  });
});
