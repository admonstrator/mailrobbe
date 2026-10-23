import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AttachmentInfo, MailHits } from "../../api/types";
import { mailDetail, transcriptView } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { ATTACHMENTS_SHOWN, MEMBERS_SHOWN } from "./AttachmentsCard";

async function attachmentsCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: /^Anhänge \(\d+\)$/ });
  return heading.closest("section")!;
}

function item(card: HTMLElement, name: string): HTMLElement {
  return within(card).getByText(name).closest("li")!;
}

/** The name of an attachment, which opens it over the page (D331). */
function opener(card: HTMLElement, name: string): HTMLElement {
  return within(item(card, name)).getByRole("button", { name });
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
    latitude: 48.1371,
    longitude: 11.5754,
  },
};

describe("attachments of a mail", () => {
  it("sit below the text and download from the MBOX and lead to their documents", async () => {
    renderApp("/mails/184221");
    const card = await attachmentsCard();
    expect(card.closest("main")).toBeTruthy();
    const body = screen.getByRole("region", { name: "Inhalt" });
    expect(body.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const contract = item(card, "Rahmenvereinbarung_2026_final.pdf");
    expect(within(contract).getByRole("img", { name: "PDF" })).toBeTruthy();
    // The kind in words, its MIME type on hover.
    const mime = within(contract).getByTitle("application/pdf");
    expect(mime.parentElement!.textContent).toBe("PDF · 14 Seiten · 168 KB · SHA-256 91ab…");
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
    // The name opens it; the links keep their order.
    expect(
      Array.from(contract.querySelectorAll("a, button"), (element) => element.textContent),
    ).toEqual(["Rahmenvereinbarung_2026_final.pdf", "Herunterladen", "auch in 5 weiteren Mails"]);

    const open = opener(card, "Rahmenvereinbarung_2026_final.pdf");
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

    fireEvent.click(opener(card, "Anruf.m4a"));
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
    fireEvent.click(opener(card, "IMG_0412.jpg"));
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

describe("protected and packed attachments of a mail (D231, D233)", () => {
  const zip: AttachmentInfo = {
    ...sheet,
    id: 905,
    filename: "Unterlagen.zip",
    mime_type: "application/zip",
    document_id: 5106,
    kind: "archive",
    text_status: "unsupported",
    pages: null,
    protection: null,
    members_status: "done",
    members: Array.from({ length: MEMBERS_SHOWN + 2 }, (_, index) => ({
      ...sheet,
      id: 950 + index,
      filename: `Beleg_${index}.pdf`,
      path: `Belege/Beleg_${index}.pdf`,
      mime_type: "application/pdf",
      document_id: 5200 + index,
      kind: "pdf" as const,
      size: 20_480,
      members_status: null,
      members: [],
    })),
  };

  it("say whether they need a password or were opened with one", async () => {
    renderApp(
      "/mails/184221",
      withAttachments([
        { ...pdf, protection: "open" },
        { ...sheet, protection: "locked", text_status: "encrypted", preview: "html" },
      ]),
    );
    const card = await attachmentsCard();
    const opened = item(card, "Rahmenvereinbarung_2026_final.pdf");
    const openedNote = within(opened).getByText("Geöffnet");
    expect(openedNote.getAttribute("title")).toBe(
      "Verschlüsselt, mit einem gefundenen Kennwort geöffnet",
    );
    const locked = item(card, "Aenderungsprotokoll.xlsx");
    expect(within(locked).getByText("Kennwort unbekannt").getAttribute("title")).toBe(
      "Verschlüsselt, das Kennwort ist nicht bekannt",
    );
    // The protection says it already; and nothing previews a locked file.
    expect(within(locked).queryByText("Verschlüsselt")).toBeNull();
    fireEvent.click(opener(card, "Aenderungsprotokoll.xlsx"));
    const overlay = screen.getByRole("dialog", { name: "Aenderungsprotokoll.xlsx" });
    expect(within(overlay).getByText(/mit einem Kennwort geschützt/)).toBeTruthy();
    expect(within(overlay).queryByTitle(/Vorschau von/)).toBeNull();
  });

  it("preview an opened PDF decrypted", async () => {
    const { calls } = renderApp("/mails/184221", withAttachments([{ ...pdf, protection: "open" }]));
    const card = await attachmentsCard();
    fireEvent.click(opener(card, "Rahmenvereinbarung_2026_final.pdf"));
    const overlay = screen.getByRole("dialog", { name: "Rahmenvereinbarung_2026_final.pdf" });
    await within(overlay).findByTitle("PDF-Vorschau von Rahmenvereinbarung_2026_final.pdf");
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.pathname === "/api/attachments/901/content"),
      ).toHaveLength(1),
    );
    const read = calls.find((call) => call.url.pathname === "/api/attachments/901/content")!;
    expect(read.url.searchParams.get("decrypted")).toBe("true");
  });

  it("list a container's documents below it, the first few and the rest on request", async () => {
    renderApp("/mails/184221", withAttachments([pdf, zip]));
    const card = await attachmentsCard();
    const container = item(card, "Unterlagen.zip");
    const members = within(container).getByRole("list", { name: "Inhalt von Unterlagen.zip" });
    expect(within(members).getAllByRole("listitem")).toHaveLength(MEMBERS_SHOWN);
    const first = within(members).getByRole("link", { name: "Belege/Beleg_0.pdf" });
    expect(first.getAttribute("href")).toBe("/anhaenge/5200");
    expect(first.closest("li")!.textContent).toBe("Belege/Beleg_0.pdf20 KB");
    // Unpacked: nothing to say about it.
    expect(within(container).queryByText(/ausgepackt|Kennwort/)).toBeNull();

    fireEvent.click(
      within(container).getByRole("button", {
        name: `alle ${MEMBERS_SHOWN + 2} Einträge anzeigen`,
      }),
    );
    expect(within(members).getAllByRole("listitem")).toHaveLength(MEMBERS_SHOWN + 2);
    // The mail's own attachments are counted, not the documents inside them.
    expect(within(card).getByRole("heading").textContent).toBe("Anhänge (2)");
  });

  it("say when a container is not unpacked yet or some entries need a password", async () => {
    renderApp(
      "/mails/184221",
      withAttachments([
        { ...pdf, members_status: null, members: [] },
        { ...zip, members_status: null, members: [] },
        {
          ...zip,
          id: 906,
          filename: "Gehaelter.7z",
          protection: "locked",
          members_status: "locked",
          members: zip.members!.slice(0, 1),
        },
      ]),
    );
    const card = await attachmentsCard();
    expect(
      within(item(card, "Unterlagen.zip")).getByText(
        "Noch nicht ausgepackt, das geschieht beim nächsten Import.",
      ),
    ).toBeTruthy();
    const sevenZip = item(card, "Gehaelter.7z");
    expect(
      within(sevenZip).getByText("Einträge brauchen ein Kennwort, das noch nicht bekannt ist."),
    ).toBeTruthy();
    expect(within(sevenZip).getByRole("link", { name: "Belege/Beleg_0.pdf" })).toBeTruthy();
    // Any other attachment says nothing about unpacking.
    expect(
      within(item(card, "Rahmenvereinbarung_2026_final.pdf")).queryByText(/ausgepackt/),
    ).toBeNull();
  });

  it("show a document inside a container that holds a search word, wherever it stands", async () => {
    const many = Array.from({ length: ATTACHMENTS_SHOWN }, (_, index): AttachmentInfo => ({
      ...sheet,
      id: 1000 + index,
      filename: `Anlage_${index}.xlsx`,
    }));
    renderApp(`/mails/184221?${new URLSearchParams({ q: "Haftung" })}`, (call) => {
      if (call.url.pathname === "/api/mails/184221") {
        return { ...mailDetail, attachments: [...many, zip] };
      }
      if (call.url.pathname === "/api/mails/184221/hits") {
        return {
          words: ["haftung"],
          stems: [],
          in_mail: false,
          attachments: [{ attachment_id: 956, in_name: false, snippet: "die Haftung" }],
        };
      }
      return fixtureApi(call);
    });
    const card = await attachmentsCard();
    const hit = await within(card).findByRole("link", { name: "Belege/Beleg_6.pdf" });
    const member = hit.closest("li")!;
    expect(member.id).toBe("anhang-956");
    expect(member.textContent).toContain("…die Haftung…");
    // Beyond the first eight attachments and the first five entries, listed for the hit.
    expect(within(card).getAllByRole("listitem")).toHaveLength(
      ATTACHMENTS_SHOWN + 1 + MEMBERS_SHOWN + 1,
    );
    // The search hits name it by its path.
    expect(await screen.findByRole("button", { name: "Belege/Beleg_6.pdf" })).toBeTruthy();
  });
});

describe("text recognition from a mail's attachments", () => {
  const scan: AttachmentInfo = {
    ...pdf,
    id: 904,
    filename: "Scan_0042.pdf",
    document_id: 4042,
    text_status: "scanned",
    ocr: "readable",
  };

  it("starts a run for just that document at once", async () => {
    const started = { ...scan, ocr: "queued" as const };
    let queued = false;
    const { calls } = renderApp("/mails/184221", (call) => {
      if (call.url.pathname === "/api/ai/tasks") {
        queued = true;
        return { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "started" };
      }
      return withAttachments([queued ? started : scan, sheet])(call);
    });
    const card = await attachmentsCard();
    fireEvent.click(within(card).getByRole("button", { name: "Text von Scan_0042.pdf erkennen" }));
    await waitFor(() =>
      expect(calls.filter((call) => call.url.pathname === "/api/ai/tasks")).toHaveLength(1),
    );
    expect(calls.find((call) => call.url.pathname === "/api/ai/tasks")!.body).toEqual({
      document_ids: [4042],
      single: true,
      start: true,
    });
    // The mail is asked again and the row says the recognition is under way.
    expect(await within(card).findByText("Texterkennung läuft")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: /erkennen$/ })).toBeNull();
  });

  it("says when an import keeps the run from starting", async () => {
    renderApp("/mails/184221", (call) =>
      call.url.pathname === "/api/ai/tasks"
        ? { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "busy" }
        : withAttachments([scan, sheet])(call),
    );
    const card = await attachmentsCard();
    fireEvent.click(within(card).getByRole("button", { name: "Text von Scan_0042.pdf erkennen" }));
    expect(await within(card).findByText(/Gerade läuft ein Import/)).toBeTruthy();
  });

  it("marks recognised texts and files without writing, and offers nothing else", async () => {
    renderApp(
      "/mails/184221",
      withAttachments([
        { ...scan, ocr: "recognised" },
        { ...photo, ocr: "no_text" },
      ]),
    );
    const card = await attachmentsCard();
    expect(within(item(card, "Scan_0042.pdf")).getByText("Text maschinell erkannt")).toBeTruthy();
    expect(within(item(card, "IMG_0412.jpg")).getByText("keine Schrift erkannt")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: /erkennen$/ })).toBeNull();
  });
});

describe("transcription from a mail's attachments (D296)", () => {
  const voice: AttachmentInfo = {
    ...pdf,
    id: 960,
    filename: "Sprachnachricht_Vorstand.ogg",
    mime_type: "audio/ogg",
    size: 98_304,
    document_id: 5160,
    kind: "media",
    text_status: "unsupported",
    pages: null,
    document_mails: 1,
    preview: "audio",
    metadata: null,
    transcript: "transcribable",
  };
  const heard: AttachmentInfo = {
    ...voice,
    text_status: "text",
    transcript: "transcribed",
    duration: 192.4,
  };

  it("transcribes a recording at once, where Text erkennen would stand", async () => {
    let queued = false;
    const { calls } = renderApp("/mails/184221", (call) => {
      if (call.url.pathname === "/api/ai/tasks") {
        queued = true;
        return { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "started" };
      }
      const now = queued ? { ...voice, transcript: "queued" as const } : voice;
      return withAttachments([pdf, now])(call);
    });
    const card = await attachmentsCard();
    const row = item(card, "Sprachnachricht_Vorstand.ogg");
    // After the document link, as "Text erkennen" stands for a scan.
    expect(Array.from(row.querySelectorAll("a, button"), (element) => element.textContent)).toEqual(
      ["Sprachnachricht_Vorstand.ogg", "Herunterladen", "Zum Dokument", "Transkribieren"],
    );
    fireEvent.click(
      within(row).getByRole("button", { name: "Sprachnachricht_Vorstand.ogg transkribieren" }),
    );
    await waitFor(() =>
      expect(calls.filter((call) => call.url.pathname === "/api/ai/tasks")).toHaveLength(1),
    );
    expect(calls.find((call) => call.url.pathname === "/api/ai/tasks")!.body).toEqual({
      document_ids: [5160],
      single: true,
      start: true,
      kind: "transcribe",
    });
    expect(await within(card).findByText("Transkript wird erstellt")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: /transkribieren$/ })).toBeNull();
  });

  it("say how the transcription went, with the recording's length", async () => {
    renderApp(
      "/mails/184221",
      withAttachments([
        heard,
        { ...voice, id: 961, filename: "Rauschen.mp3", transcript: "no_text" },
      ]),
    );
    const card = await attachmentsCard();
    const row = item(card, "Sprachnachricht_Vorstand.ogg");
    expect(within(row).getByText("transkribiert")).toBeTruthy();
    expect(within(row).getByTitle("Länge der Aufnahme").textContent).toBe("3:12");
    expect(within(item(card, "Rauschen.mp3")).getByText("keine Sprache erkannt")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: /transkribieren$/ })).toBeNull();
  });

  it("show the transcript under the player, the search words marked", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const hits: MailHits = {
      words: ["Rat"],
      stems: ["rat"],
      in_mail: false,
      attachments: [
        {
          attachment_id: 960,
          in_name: false,
          snippet: "Die Sitzung mit dem Rat wird auf Donnerstag verschoben.",
          in_text: true,
          machine: true,
        },
      ],
      whole_word: false,
      in_subject: false,
      in_body: false,
      counts: null,
    };
    renderApp(`/mails/184221?${new URLSearchParams({ q: "Rat" })}`, (call) => {
      const path = call.url.pathname;
      if (path === "/api/mails/184221/hits") return hits;
      if (path === "/api/documents/5160/transcript") return transcriptView;
      return withAttachments([pdf, heard])(call);
    });
    const card = await attachmentsCard();
    const row = item(card, "Sprachnachricht_Vorstand.ogg");
    // The hit line says the text was transcribed, and so does the search hits card.
    const mark = await within(row).findByText("maschinell transkribiert");
    expect(mark.title).toMatch(/aus dem Ton der Aufnahme transkribiert/);
    const found = screen.getByRole("region", { name: "Suchtreffer" });
    expect(within(found).getByText("maschinell transkribiert")).toBeTruthy();

    fireEvent.click(opener(card, "Sprachnachricht_Vorstand.ogg"));
    const overlay = screen.getByRole("dialog", { name: "Sprachnachricht_Vorstand.ogg" });
    const lines = await within(overlay).findByRole("list", { name: "Zeilen des Transkripts" });
    expect([...lines.querySelectorAll("mark")].map((marked) => marked.textContent)).toEqual([
      "Rat",
      "Rat",
    ]);
    const audio = overlay.querySelector("audio")!;
    fireEvent.click(within(lines).getByRole("button", { name: "Ab 1:05 abspielen" }));
    expect(audio.currentTime).toBe(65.3);
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.timeUpdate(audio);
    expect(within(lines).getByRole("listitem", { current: true }).textContent).toContain(
      "der Rat wartet",
    );
    play.mockRestore();
  });

  it("share a spoken transcript as a picture headed by this mail (D298)", async () => {
    renderApp("/mails/184221", (call) => {
      if (call.url.pathname === "/api/documents/5160/transcript") return transcriptView;
      return withAttachments([
        pdf,
        heard,
        { ...heard, id: 961, filename: "Rauschen.mp3", transcript: "no_text" },
      ])(call);
    });
    const card = await attachmentsCard();
    fireEvent.click(opener(card, "Rauschen.mp3"));
    const silent = screen.getByRole("dialog", { name: "Rauschen.mp3" });
    expect(within(silent).queryByRole("button", { name: "Als Bild teilen" })).toBeNull();
    fireEvent.click(within(silent).getByRole("button", { name: "Schließen" }));

    fireEvent.click(opener(card, "Sprachnachricht_Vorstand.ogg"));
    const overlay = screen.getByRole("dialog", { name: "Sprachnachricht_Vorstand.ogg" });
    fireEvent.click(within(overlay).getByRole("button", { name: "Als Bild teilen" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Transkript als Bild für Soziale Medien",
    });
    expect(
      within(dialog).getByRole("img", { name: "Vorschau des Bildes" }).getAttribute("src"),
    ).toBe("/api/documents/5160/social.png?shape=portrait&attachment=960");
  });

  it("show a recording without a transcript as before", async () => {
    const { calls } = renderApp("/mails/184221", withAttachments([pdf, voice]));
    const card = await attachmentsCard();
    fireEvent.click(opener(card, "Sprachnachricht_Vorstand.ogg"));
    const overlay = screen.getByRole("dialog", { name: "Sprachnachricht_Vorstand.ogg" });
    await waitFor(() => expect(overlay.querySelector("audio")).toBeTruthy());
    expect(within(overlay).queryByRole("list")).toBeNull();
    expect(calls.some((call) => call.url.pathname.endsWith("/transcript"))).toBe(false);
  });
});
