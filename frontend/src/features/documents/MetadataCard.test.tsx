import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentMetadata } from "../../api/types";
import { formatDateTime } from "../../lib/format";
import { documentDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

async function metadataCard(): Promise<HTMLElement> {
  const title = await screen.findByRole("heading", { name: "Metadaten" });
  return title.closest("section")!;
}

function group(card: HTMLElement, name: string): HTMLElement {
  return within(card).getByRole("region", { name });
}

const NOTHING = { error: null, fields: {}, summary: null };

const withMetadata = (metadata: DocumentMetadata) => (call: ApiCall) =>
  call.url.pathname === "/api/documents/5101" ? { ...documentDetail, metadata } : fixtureApi(call);

describe("the card Metadaten of a document", () => {
  it("shows every field in its group with its source, and links author and program", async () => {
    renderApp("/anhaenge/5101");
    const card = await metadataCard();

    const author = group(card, "Autor");
    expect(within(author).getByText("PDF").closest("dt")!.textContent).toBe("Autor PDF");
    expect(within(author).getAllByText("Peter Hofmann")).toHaveLength(2); // PDF and XMP
    const dates = group(card, "Daten");
    expect(within(dates).getByText(formatDateTime("2026-10-08T15:40:12Z", true)).title).toBe(
      "in der Datei: 2026-10-08T17:40:12+02:00",
    );
    expect(within(group(card, "Weitere Angaben")).getByText("Einkauf")).toBeTruthy();
    expect(within(card).queryByRole("region", { name: "Ort" })).toBeNull();

    expect(
      within(card).getByRole("link", { name: "Alle Dokumente dieses Autors" }).getAttribute("href"),
    ).toBe("/anhaenge?author=Peter+Hofmann");
    expect(
      within(card)
        .getByRole("link", { name: "Alle Dokumente dieses Programms" })
        .getAttribute("href"),
    ).toBe("/anhaenge?program=Microsoft+Word+f%C3%BCr+Microsoft+365");
    expect(within(card).getByText(/Mailrobbe prüft diese Angaben nicht/)).toBeTruthy();
  });

  it("shows the camera, the time taken and the place of a photo", async () => {
    renderApp("/anhaenge/5105");
    const card = await metadataCard();

    expect(within(group(card, "Kamera")).getByText("Canon EOS 80D")).toBeTruthy();
    const capture = group(card, "Aufnahme");
    expect(within(capture).getByText("02.10.2026 14:31:07 (ohne Zeitzone)")).toBeTruthy();
    const place = group(card, "Ort");
    expect(within(place).getByText("53.5438333, 9.9661667")).toBeTruthy();
    const map = within(place).getByRole("link", { name: "auf OpenStreetMap ansehen" });
    expect(map.getAttribute("href")).toBe(
      "https://www.openstreetmap.org/?mlat=53.5438333&mlon=9.9661667#map=16/53.5438333/9.9661667",
    );
    expect(map.getAttribute("target")).toBe("_blank");
    expect(map.getAttribute("rel")).toBe("noopener noreferrer");
    expect(within(place).getByText("12,5 m")).toBeTruthy();
  });

  it("says when the file was not read yet", async () => {
    renderApp("/anhaenge/5101", withMetadata({ status: "pending", ...NOTHING }));
    const card = await metadataCard();
    expect(card.textContent).toContain(
      "Noch nicht gelesen: beim nächsten Import-Lauf unter Import.",
    );
    expect(within(card).getByRole("link", { name: "Import" }).getAttribute("href")).toBe("/import");
    expect(within(card).queryByText(/Mailrobbe prüft/)).toBeNull();
  });

  it("says when the file says nothing", async () => {
    renderApp("/anhaenge/5101", withMetadata({ status: "empty", ...NOTHING }));
    const card = await metadataCard();
    expect(within(card).getByText("Die Datei enthält keine Metadaten.")).toBeTruthy();
  });

  it("names a damaged part", async () => {
    const error = "EXIF: the value of tag 0x0131 lies outside the data";
    renderApp("/anhaenge/5101", withMetadata({ ...documentDetail.metadata, error }));
    const card = await metadataCard();
    expect(within(card).getByText(/Ein Teil der Datei ist beschädigt/)).toBeTruthy();
    expect(within(card).getByText(error)).toBeTruthy();
    expect(within(card).getByRole("region", { name: "Autor" })).toBeTruthy();
  });

  it("calls an encrypted file encrypted, not damaged", async () => {
    const error = "encrypted: the information dictionary needs a password";
    renderApp("/anhaenge/5101", withMetadata({ ...documentDetail.metadata, error }));
    const card = await metadataCard();
    expect(within(card).getByText(/Die Datei ist verschlüsselt; aufgeführt ist/)).toBeTruthy();
    expect(within(card).queryByText(/beschädigt/)).toBeNull();
  });

  it("names a failure", async () => {
    const error = "encrypted: needs a password";
    renderApp("/anhaenge/5101", withMetadata({ ...NOTHING, status: "failed", error }));
    const card = await metadataCard();
    expect(within(card).getByText(/Die Metadaten ließen sich nicht lesen/)).toBeTruthy();
    expect(within(card).getByText(error)).toBeTruthy();
  });
});
