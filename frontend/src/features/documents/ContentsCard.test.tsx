import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentDetail, DocumentMember } from "../../api/types";
import { containerDocument } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { ENTRIES_SHOWN } from "./ContentsCard";

const withContainer = (patch: Partial<DocumentDetail>) => (call: ApiCall) =>
  call.url.pathname === "/api/documents/5106"
    ? { ...containerDocument, ...patch }
    : fixtureApi(call);

const members = containerDocument.members!;

async function contentsCard(name: string | RegExp): Promise<HTMLElement> {
  return (await screen.findByRole("heading", { name })).closest("section")!;
}

describe("a container's contents", () => {
  it("lists the entries in order with size, status and their documents", async () => {
    renderApp("/anhaenge/5106");
    const card = await contentsCard("Inhalt (4)");
    expect(card.closest("main")).toBeTruthy();
    expect(card.textContent).toContain(
      "Einträge brauchen ein Kennwort, das noch nicht bekannt ist; was sich ohne lesen ließ, ist ausgepackt.",
    );
    const rows = within(card).getAllByRole("listitem");
    expect(rows.map((row) => row.firstElementChild!.nextElementSibling!.textContent)).toEqual([
      "Vorstand/Protokoll_2019-03.docx",
      "Vorstand/Gehaelter_2019.xlsx",
      "Video/Mitgliederversammlung.mp4",
      "Scans/Beleg_017.pdf",
    ]);
    expect(
      within(rows[0])
        .getByRole("link", { name: "Vorstand/Protokoll_2019-03.docx" })
        .getAttribute("href"),
    ).toBe("/anhaenge/5111");
    expect(rows[0].textContent).toContain("31 KB");
    expect(within(rows[1]).getByText("Kennwort unbekannt")).toBeTruthy();
    expect(within(rows[1]).queryByRole("link")).toBeNull();
    expect(within(rows[2]).getByText("Zu groß")).toBeTruthy();
    expect(within(rows[3]).getByText("Gescannt")).toBeTruthy();
    expect(within(rows[3]).getByRole("link").getAttribute("href")).toBe("/anhaenge/5112");
    // A container is no file to decrypt.
    expect(screen.queryByRole("link", { name: "Entschlüsselt herunterladen" })).toBeNull();
  });

  it("names every status of an entry, with the technical reason of a failure", async () => {
    const entry = (patch: Partial<DocumentMember>): DocumentMember => ({
      ...members.entries[1],
      ...patch,
    });
    renderApp(
      "/anhaenge/5106",
      withContainer({
        members: {
          status: "done",
          error: null,
          entries: [
            entry({ position: 0, path: "a.pdf", status: "too_many", size: null }),
            entry({ position: 1, path: "b.pdf", status: "failed", error: "CRC Failed : b.pdf" }),
            entry({ position: 2, path: "c.pdf", status: "document", document_id: null }),
            entry({
              position: 3,
              path: "d.pdf",
              status: "document",
              document_id: 5113,
              protection: "locked",
              text_status: "encrypted",
            }),
          ],
        },
      }),
    );
    const card = await contentsCard("Inhalt (4)");
    const rows = within(card).getAllByRole("listitem");
    expect(within(rows[0]).getByText("Zu viele Einträge")).toBeTruthy();
    expect(within(rows[1]).getByText("Fehler").getAttribute("title")).toBe("CRC Failed : b.pdf");
    expect(within(rows[2]).getByText("Dokument ab dem nächsten Import")).toBeTruthy();
    expect(
      within(rows[3]).getByRole("img", { name: "Verschlüsselt, das Kennwort ist nicht bekannt" }),
    ).toBeTruthy();
    // Unpacked: nothing to say about the container.
    expect(card.querySelector("p")).toBeNull();
  });

  it("reads as the attached mail's attachments for an attached mail", async () => {
    renderApp(
      "/anhaenge/5106",
      withContainer({ kind: "email", name: "Angebot.eml", mime_type: "message/rfc822" }),
    );
    expect(await contentsCard("Anhänge der angehängten Mail (4)")).toBeTruthy();
  });

  it.each([
    [{ status: null, opened: false }, "Noch nicht ausgepackt. Das geschieht beim nächsten Import."],
    [
      { status: null, opened: true },
      "Mit dem Kennwort geöffnet; der nächste Import packt den Inhalt aus.",
    ],
    [
      { status: "too_deep", opened: false },
      "Die Datei steckt selbst in einem Archiv oder einer angehängten Mail. Mailrobbe packt nur zwei Ebenen aus; ihr Inhalt bleibt verpackt.",
    ],
    [
      { status: "unsupported", opened: false },
      "Dieses Format packt Mailrobbe nicht aus (etwa RAR, tar oder gzip), nur ZIP, 7z und angehängte Mails.",
    ],
    [
      { status: "unreadable", opened: false },
      "Die MBOX-Datei fehlt oder hat sich geändert. Der nächste Import versucht es erneut.",
    ],
  ] as const)("says how the unpacking stands: %o", async ({ status, opened }, text) => {
    renderApp(
      "/anhaenge/5106",
      withContainer({
        protection: opened ? "open" : null,
        members: { status, error: null, entries: [] },
      }),
    );
    const card = await contentsCard("Inhalt");
    expect(card.textContent).toBe(`Inhalt${text}`);
  });

  it("shows why the unpacking failed", async () => {
    renderApp(
      "/anhaenge/5106",
      withContainer({
        members: { status: "failed", error: "Can not open the file as archive", entries: [] },
      }),
    );
    const card = await contentsCard("Inhalt");
    expect(card.textContent).toContain("Das Auspacken ist fehlgeschlagen.");
    expect(within(card).getByText("Can not open the file as archive").tagName).toBe("CODE");
  });

  it("says when an unpacked archive is empty", async () => {
    renderApp(
      "/anhaenge/5106",
      withContainer({ members: { status: "done", error: null, entries: [] } }),
    );
    expect((await contentsCard("Inhalt")).textContent).toContain("Das Archiv ist leer.");
  });

  it("shows the first entries of a long archive, then all", async () => {
    const entries = Array.from({ length: ENTRIES_SHOWN + 7 }, (_, position) => ({
      ...members.entries[0],
      position,
      path: `Ordner/Datei_${position}.docx`,
      document_id: 6000 + position,
    }));
    renderApp(
      "/anhaenge/5106",
      withContainer({ members: { status: "done", error: null, entries } }),
    );
    const card = await contentsCard(`Inhalt (${ENTRIES_SHOWN + 7})`);
    expect(within(card).getAllByRole("listitem")).toHaveLength(ENTRIES_SHOWN);
    fireEvent.click(
      within(card).getByRole("button", { name: `alle ${ENTRIES_SHOWN + 7} anzeigen` }),
    );
    expect(within(card).getAllByRole("listitem")).toHaveLength(ENTRIES_SHOWN + 7);
    expect(within(card).queryByRole("button")).toBeNull();
  });
});

describe("a member document", () => {
  it("says which containers hold it, and where in them", async () => {
    renderApp("/anhaenge/5111");
    const heading = await screen.findByRole("heading", { name: "Enthalten in" });
    const card = heading.closest("section")!;
    expect(card.closest("aside")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Unterlagen.zip" }).getAttribute("href")).toBe(
      "/anhaenge/5106",
    );
    expect(within(card).getByText("Vorstand/Protokoll_2019-03.docx")).toBeTruthy();
    // It is no container itself.
    expect(screen.queryByRole("heading", { name: /^Inhalt/ })).toBeNull();
  });

  it("says nothing about containers for a document found only as an attachment", async () => {
    renderApp("/anhaenge/5101");
    await screen.findByRole("heading", { level: 1, name: "Rahmenvereinbarung_2026_final.pdf" });
    expect(screen.queryByRole("heading", { name: "Enthalten in" })).toBeNull();
    expect(screen.queryByRole("heading", { name: /^Verschlüsselt/ })).toBeNull();
  });
});
