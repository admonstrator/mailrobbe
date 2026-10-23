import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { readHistory } from "../../lib/history";
import { documentDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { stubIntersectionObserver } from "../../test/scroll";

function card(heading: string | RegExp): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("section")!;
}

/** The figure of the quiet line "Kennzahlen" that names label, and its title. */
function figure(label: string): [string, string] {
  const list = screen.getByRole("list", { name: "Kennzahlen" });
  const item = within(list)
    .getAllByRole("listitem")
    .find((one) => one.textContent!.includes(label))!;
  return [item.textContent!, item.title];
}

const withDocument = (patch: Partial<typeof documentDetail>) => (call: ApiCall) =>
  call.url.pathname === "/api/documents/5101" ? { ...documentDetail, ...patch } : fixtureApi(call);

const hash = documentDetail.sha256!;

describe("document page", () => {
  it("marks a text an AI run recognised in the header", async () => {
    renderApp("/anhaenge/5101", withDocument({ text_origin: "ocr" }));

    expect(await screen.findByText("maschinell erkannt")).toBeTruthy();
    expect(screen.getByText(/^Der Text wurde aus den Seitenbildern erkannt/)).toBeTruthy();
    expect(screen.queryByText(/^Der Text ist ausgelesen/)).toBeNull();
  });

  it("shows what the document is, its figures, names and persons", async () => {
    renderApp("/anhaenge/5101");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Rahmenvereinbarung_2026_final.pdf" }),
    ).toBeTruthy();
    expect(document.title).toBe("Rahmenvereinbarung_2026_final.pdf · Mailrobbe");
    const path = screen.getByRole("navigation", { name: "Pfad" });
    expect(within(path).getByRole("link", { name: "Anhänge" }).getAttribute("href")).toBe(
      "/anhaenge",
    );
    expect(screen.getByText("PDF · 14 Seiten · 168 KB · application/pdf")).toBeTruthy();
    expect(screen.getByText(hash)).toBeTruthy();
    expect(
      screen.getByText(
        "Der Text ist ausgelesen; die Volltextsuche findet das Dokument über seine Wörter.",
      ),
    ).toBeTruthy();

    const first = screen.getByRole("link", { name: "Vertrag Nordstahl: Änderungswünsche Einkauf" });
    expect(first.getAttribute("href")).toBe("/mails/183644");

    const download = screen.getByRole("link", { name: "Herunterladen" });
    expect(download.getAttribute("href")).toBe("/api/attachments/901/content");
    expect(download.hasAttribute("download")).toBe(true);
    expect(screen.queryByRole("img", { name: /Vorschau/ })).toBeNull();

    expect(figure("Mails")).toEqual(["6 Mails", "ohne Duplikate"]);
    expect(figure("Anhänge")).toEqual(["7 Anhänge", "Vorkommen, mit Duplikaten"]);
    expect(figure("erstmals")[0]).toBe("erstmals 28.09.2026");
    expect(figure("erstmals")[1]).toMatch(/^28\.09\.2026,? \d\d:\d\d Uhr$/);
    expect(figure("zuletzt")[0]).toBe("zuletzt 18.10.2026");

    const names = card("Dateinamen (3)");
    expect(
      within(names)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Rahmenvereinbarung_2026_final.pdf4×",
      "Rahmenvereinbarung 2026.pdf2×",
      "RV2026_unterschrieben.pdf1×",
    ]);

    const senders = card("Absender (3)");
    expect(
      within(senders)
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual(["/personen/11", "/personen/14", "/personen/13"]);
    expect(within(senders).getByText("3")).toBeTruthy();
    expect(within(senders).queryByText(/weitere/)).toBeNull();

    const recipients = card("Empfänger (14)");
    expect(within(recipients).getAllByRole("link")).toHaveLength(9);
    expect(within(recipients).getByText("und 5 weitere")).toBeTruthy();
  });

  it("lists who sent it when to whom, oldest first, as mails of the mail list", async () => {
    const { calls } = renderApp("/anhaenge/5101");
    const mails = await screen.findByRole("heading", {
      name: "Wer hat dieses Dokument wann an wen geschickt",
    });
    const section = mails.closest("section")!;
    const subject = await within(section).findByRole("link", {
      name: "Vertrag Nordstahl: Änderungswünsche Einkauf",
    });
    const listQuery = "hide_duplicates=true&document=5101&sort=date_asc";
    expect(subject.getAttribute("href")).toBe(`/mails/183644?${listQuery}`);
    expect(within(section).getAllByRole("row")).toHaveLength(7);
    expect(
      within(section)
        .getAllByRole("columnheader")
        .map((th) => th.textContent),
    ).toEqual(["DKIM", "Von", "An", "Betreff", "Datum"]);
    expect(within(section).getByText("1–6 von 6")).toBeTruthy();
    expect(
      within(section)
        .getByRole("link", { name: "Alle Mails mit diesem Dokument" })
        .getAttribute("href"),
    ).toBe(`/mails?${listQuery}`);

    const request = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(request.url.searchParams.get("document")).toBe("5101");
    expect(request.url.searchParams.get("sort")).toBe("date_asc");
    expect(request.url.searchParams.get("hide_duplicates")).toBe("true");
  });

  it("loads the text only when asked for", async () => {
    const { calls } = renderApp("/anhaenge/5101");
    const button = await screen.findByRole("button", { name: "Text anzeigen" });
    const textCalls = () => calls.filter((call) => call.url.pathname.endsWith("/text"));
    expect(textCalls()).toHaveLength(0);
    expect(card("Ausgelesener Text").textContent).not.toContain("gekürzt");

    fireEvent.click(button);
    expect(await screen.findByText(/Die Spende über 12\.500,00 EUR/)).toBeTruthy();
    expect(textCalls()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Text ausblenden" })).toHaveProperty(
      "ariaExpanded",
      "true",
    );
    expect(screen.getByText(/\d+ Zeichen/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Text ausblenden" }));
    expect(screen.queryByText(/Die Spende über/)).toBeNull();
  });

  it("says when the text was cut", async () => {
    renderApp("/anhaenge/5101", withDocument({ text_truncated: true }));
    const text = await screen.findByRole("heading", { name: "Ausgelesener Text" });
    expect(within(text.closest("section")!).getByText("gekürzt")).toBeTruthy();
    expect(screen.getByText(/Gespeichert sind die ersten 400\.000 Zeichen\./)).toBeTruthy();
  });

  it("explains a scan and a failure, and offers no text for them", async () => {
    renderApp("/anhaenge/5101", withDocument({ text_status: "scanned" }));
    expect(
      await screen.findByText(/Ein gescanntes PDF: Die Seiten sind Bilder ohne Textebene/),
    ).toBeTruthy();
    expect(screen.getByText("Gescannt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Text anzeigen" })).toBeNull();
  });

  it("shows the technical reason of a failure", async () => {
    renderApp(
      "/anhaenge/5101",
      withDocument({ text_status: "failed", text_error: "PdfReadError: EOF marker not found" }),
    );
    expect(await screen.findByText("PdfReadError: EOF marker not found")).toBeTruthy();
    expect(screen.getByText(/Der Text ließ sich nicht auslesen/)).toBeTruthy();
  });

  it("shows a raster image as a preview", async () => {
    renderApp("/anhaenge/5105");
    const preview = await screen.findByRole("img", { name: "Vorschau von IMG_2041.jpg" });
    expect(preview.getAttribute("src")).toBe("/api/attachments/9105/content");
    expect(screen.getByText(/Aus diesem Format liest Mailrobbe keinen Text/)).toBeTruthy();
    expect(screen.getByText("Dateiname")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Ausgelesener Text" })).toBeNull();
    expect(preview.closest("aside")).toBeTruthy();
    expect(screen.queryByText(/Keine Vorschau im Browser/)).toBeNull();
  });

  it.each([
    ["the picture", () => screen.getByRole("img", { name: "Vorschau von IMG_2041.jpg" })],
    ["Großansicht", () => screen.getByRole("button", { name: "Großansicht" })],
  ])("opens the large view of the image by a click on %s", async (_, target) => {
    renderApp("/anhaenge/5105");
    await screen.findByRole("img", { name: "Vorschau von IMG_2041.jpg" });
    const opener = target();
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "IMG_2041.jpg" });
    const large = within(dialog).getByRole("img", { name: "Großansicht von IMG_2041.jpg" });
    expect(large.getAttribute("src")).toBe("/api/attachments/9105/content");
    expect(
      within(dialog).getByRole("link", { name: "IMG_2041.jpg herunterladen" }).getAttribute("href"),
    ).toBe("/api/attachments/9105/content");
    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps name, kind, size and the download in a bar once the header is scrolled away", async () => {
    const observer = stubIntersectionObserver();
    renderApp("/anhaenge/5101");
    await screen.findByRole("heading", { level: 1, name: "Rahmenvereinbarung_2026_final.pdf" });
    const bar = () => screen.queryByRole("region", { name: "Kopfzeile des Dokuments" });
    expect(bar()).toBeNull();
    observer.place("above");
    const compact = bar()!;
    expect(within(compact).getByTitle("Rahmenvereinbarung_2026_final.pdf").textContent).toBe(
      "Rahmenvereinbarung_2026_final.pdf",
    );
    expect(within(compact).getByText("PDF · 14 Seiten · 168 KB")).toBeTruthy();
    expect(within(compact).getByRole("link", { name: "Herunterladen" }).getAttribute("href")).toBe(
      "/api/attachments/901/content",
    );
    observer.place("visible");
    expect(bar()).toBeNull();
  });

  it("says so when the browser cannot show the image", async () => {
    renderApp("/anhaenge/5105");
    fireEvent.error(await screen.findByRole("img", { name: "Vorschau von IMG_2041.jpg" }));
    expect(
      screen.getByText(
        "Der Browser kann dieses Bild nicht anzeigen. Herunterladen lässt es sich trotzdem.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("img", { name: /Vorschau/ })).toBeNull();
  });

  it.each([
    ["pdf", "PDF-Vorschau von Rahmenvereinbarung_2026_final.pdf"],
    ["html", "Vorschau von Rahmenvereinbarung_2026_final.pdf"],
    ["audio", "Rahmenvereinbarung_2026_final.pdf"],
    ["video", "Rahmenvereinbarung_2026_final.pdf"],
  ] as const)("shows a %s preview in a card of the main column", async (preview, title) => {
    renderApp("/anhaenge/5101", withDocument({ preview }));
    const shown = await screen.findByTitle(title);
    const previewCard = card("Vorschau");
    expect(previewCard.contains(shown)).toBe(true);
    expect(previewCard.closest("main")).toBeTruthy();
    expect(screen.queryByText(/Keine Vorschau im Browser/)).toBeNull();
  });

  it("says when there is no preview, and where the text is", async () => {
    renderApp("/anhaenge/5101");
    const line = await screen.findByText(/Keine Vorschau im Browser, nur Download\./);
    expect(line.textContent).toBe("Keine Vorschau im Browser, nur Download. Text siehe unten.");
    expect(line.previousElementSibling!.textContent).toBe("Vorschau");
    expect(screen.queryByRole("heading", { name: "Vorschau" })).toBeNull();
  });

  it("says only that when there is no text either", async () => {
    renderApp("/anhaenge/5101", withDocument({ text_status: "unsupported" }));
    const line = await screen.findByText(/Keine Vorschau im Browser/);
    expect(line.textContent).toBe("Keine Vorschau im Browser, nur Download.");
  });

  it("copies the SHA-256", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    renderApp("/anhaenge/5101");
    fireEvent.click(await screen.findByRole("button", { name: "Kopieren" }));
    expect(writeText).toHaveBeenCalledWith(hash);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Kopiert"));
  });

  it("keeps the download away from a file that is gone", async () => {
    renderApp("/anhaenge/5101", withDocument({ text_status: "unreadable" }));
    const download = await screen.findByText("Herunterladen");
    expect(download.getAttribute("aria-disabled")).toBe("true");
    expect(download.getAttribute("href")).toBeNull();
  });

  it("says when the document does not exist", async () => {
    renderApp("/anhaenge/9999");
    expect(await screen.findByText("Dieses Dokument gibt es nicht.")).toBeTruthy();
    expect(screen.getByText("Im Archiv gibt es kein Dokument mit der Nummer #9999.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zu den Anhängen" }).getAttribute("href")).toBe(
      "/anhaenge",
    );
  });

  it("says when the address names no document", async () => {
    renderApp("/anhaenge/abc");
    expect(
      await screen.findByText("Die Adresse nennt keine gültige Dokument-Nummer."),
    ).toBeTruthy();
  });
});

describe("a document's mails by page (D193)", () => {
  it("keep their page and page size in the URL of the document page", async () => {
    const { router, calls } = renderApp("/anhaenge/5101?limit=25&page=last");
    const mails = () => calls.filter((call) => call.url.pathname === "/api/mails");
    await waitFor(() => expect(mails().at(-1)!.url.searchParams.get("last")).toBe("true"));
    expect(mails().at(-1)!.url.searchParams.get("limit")).toBe("25");
    expect(mails().at(-1)!.url.searchParams.get("document")).toBe("5101");
    fireEvent.change(await screen.findByRole("combobox", { name: "Pro Seite" }), {
      target: { value: "200" },
    });
    expect(router.state.location.search).toBe("?limit=200");
    await waitFor(() => expect(mails().at(-1)!.url.searchParams.get("limit")).toBe("200"));
    expect(mails().at(-1)!.url.searchParams.has("last")).toBe(false);
  });
});

describe("the document page in the history (D333)", () => {
  it("records the file name and the mail it came with", async () => {
    renderApp("/anhaenge/5101");
    await screen.findByRole("heading", { level: 1, name: "Rahmenvereinbarung_2026_final.pdf" });
    await waitFor(() =>
      expect(readHistory()[0]).toMatchObject({
        kind: "document",
        id: 5101,
        title: "Rahmenvereinbarung_2026_final.pdf",
        subtitle: "aus „Vertrag Nordstahl: Änderungswünsche Einkauf“",
        path: "/anhaenge/5101",
      }),
    );
  });

  it("names the kind where no first mail is known", async () => {
    renderApp("/anhaenge/5101", withDocument({ first_mail: null }));
    await waitFor(() => expect(readHistory()[0]?.subtitle).toBe("PDF"));
  });
});
