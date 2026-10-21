import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EXPORT_LIMIT, type ErrorCode } from "../../api/types";
import { collectionDetail, exports } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method !== "GET");
const apiError = (status: number, code: ErrorCode) =>
  Response.json({ detail: { code, message: "refused" } }, { status });

/** The fixture backend, with the Akte's writes answered and a different answer where given. */
function backend(answer?: (call: ApiCall) => unknown) {
  return (call: ApiCall): unknown => {
    const custom = answer?.(call);
    if (custom !== undefined) return custom;
    if (call.method === "DELETE") return new Response(null, { status: 204 });
    if (call.method === "PATCH") return { ...collectionDetail, ...(call.body as object) };
    return fixtureApi(call);
  };
}

async function openExport() {
  fireEvent.click(await screen.findByRole("button", { name: "Exportieren" }));
  return screen.getByRole("dialog", { name: "Mails exportieren" });
}

describe("Akte page", () => {
  it("shows the Akte with figures, persons, searches and its newest mails", async () => {
    const { calls } = renderApp("/akten/1");
    expect(await screen.findByRole("heading", { level: 1, name: "Story Nordstahl" })).toBeTruthy();
    expect(document.title).toBe("Story Nordstahl · Mailrobbe");
    expect(screen.getByText(collectionDetail.description)).toBeTruthy();
    const tiles = screen.getAllByRole("listitem").filter((item) => item.textContent);
    const figures = Object.fromEntries(
      ["Mails", "Zeitraum", "Nicht im Archiv"].map((label) => [
        label,
        tiles.find((tile) => tile.firstChild?.textContent === label)?.lastChild?.textContent,
      ]),
    );
    expect(figures).toEqual({
      Mails: "24",
      Zeitraum: "02.09.2026 – 18.10.2026",
      "Nicht im Archiv": "1",
    });
    const anna = screen.getByRole("link", { name: "Anna Keller" });
    expect(anna.closest("li")!.textContent).toBe("Anna Keller18");
    expect(screen.getByRole("link", { name: "Nordstahl an Einkauf" }).getAttribute("href")).toBe(
      "/mails?q=from%3Anordstahl&sort=date_asc",
    );
    expect(screen.getByRole("link", { name: "In Mailliste öffnen" }).getAttribute("href")).toBe(
      "/mails?collection=1",
    );

    const mail = await screen.findByRole("link", {
      name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
    });
    expect(mail.getAttribute("href")).toBe("/mails/184221?collection=1");
    expect(mail.closest("li")!.textContent).toContain("18.10.2026");
    expect(
      screen.getByRole("link", { name: "Weitere in der Mailliste ›" }).getAttribute("href"),
    ).toBe("/mails?collection=1");
    const listed = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(listed.url.search).toBe("?collection=1");
  });

  it("edits name and description in place", async () => {
    const { calls } = renderApp("/akten/1", backend());
    fireEvent.click(await screen.findByRole("button", { name: "Name bearbeiten" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    fireEvent.change(name, { target: { value: "Story Nordstahl II" } });
    fireEvent.submit(name);
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Beschreibung bearbeiten" }));
    const description = screen.getByRole("textbox", { name: "Beschreibung" });
    fireEvent.change(description, { target: { value: "Neu gefasst." } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Beschreibung" })).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Name bearbeiten" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();

    expect(writes(calls).map((call) => [call.method, call.url.pathname, call.body])).toEqual([
      ["PATCH", "/api/collections/1", { name: "Story Nordstahl II" }],
      ["PATCH", "/api/collections/1", { description: "Neu gefasst." }],
    ]);
  });

  it("deletes the Akte after asking, and returns to the Akten", async () => {
    const { router, calls } = renderApp("/akten/1", backend());
    fireEvent.click(await screen.findByRole("button", { name: "Akte löschen" }));
    const dialog = screen.getByRole("dialog", { name: "Akte löschen" });
    expect(dialog.textContent).toContain("Ihre Mails, Notizen und Schlagworte bleiben");
    fireEvent.click(within(dialog).getByRole("button", { name: "Akte löschen" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/akten"));
    expect(writes(calls).map((call) => [call.method, call.url.pathname])).toEqual([
      ["DELETE", "/api/collections/1"],
    ]);
  });

  it("says when there is no such Akte", async () => {
    renderApp(
      "/akten/9",
      backend((call) =>
        call.url.pathname === "/api/collections/9" ? apiError(404, "not_found") : undefined,
      ),
    );
    expect(await screen.findByText("Diese Akte gibt es nicht.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zu den Akten" }).getAttribute("href")).toBe("/akten");
  });
});

describe("export dialog", () => {
  it("exports the Akte without research data unless asked", async () => {
    const { calls } = renderApp("/akten/1", backend());
    let dialog = await openExport();
    expect(dialog.textContent).toContain("24 Mails werden exportiert");
    const label = within(dialog).getByRole("textbox", { name: "Bezeichnung" });
    expect((label as HTMLInputElement).value).toBe("Story Nordstahl");
    const research = within(dialog).getByRole("checkbox", {
      name: /Notizen, Schlagworte und Bewertung beilegen/,
    });
    expect((research as HTMLInputElement).checked).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Export anlegen" }));

    dialog = await screen.findByRole("dialog", { name: "Export angelegt" });
    expect(dialog.textContent).toContain(
      "Export 3 „Story Nordstahl“: 24 Mails, ohne Rechercheangaben.",
    );
    expect(
      within(dialog).getByRole("link", { name: "ZIP herunterladen" }).getAttribute("href"),
    ).toBe(exports[0].download_url);
    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    dialog = await openExport();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Bezeichnung" }), {
      target: { value: " Für Kanzlei Weber " },
    });
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Export anlegen" }));
    await screen.findByRole("dialog", { name: "Export angelegt" });

    expect(writes(calls).map((call) => call.body)).toEqual([
      { filters: { collection: [1] }, label: "Story Nordstahl", include_research: false },
      { filters: { collection: [1] }, label: "Für Kanzlei Weber", include_research: true },
    ]);
  });

  it("refuses more than the limit", async () => {
    const { calls } = renderApp(
      "/akten/1",
      backend((call) =>
        call.url.pathname === "/api/collections/1"
          ? { ...collectionDetail, mails: EXPORT_LIMIT + 1 }
          : undefined,
      ),
    );
    const dialog = await openExport();
    expect(within(dialog).getByRole("alert").textContent).toContain(
      "Ein Export umfasst höchstens 2.000 Mails.",
    );
    const create = within(dialog).getByRole("button", { name: "Export anlegen" });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    fireEvent.submit(create.closest("form")!);
    expect(writes(calls)).toEqual([]);
  });

  it.each([
    ["too_many_mails", "Die Auswahl umfasst mehr als 2.000 Mails. Bitte enger fassen."],
    ["empty_selection", "Die Auswahl enthält keine Mail."],
  ] as const)("explains %s in German", async (code, text) => {
    // The Akte's count can be out of date: the API decides.
    renderApp(
      "/akten/1",
      backend((call) => (call.method === "POST" ? apiError(400, code) : undefined)),
    );
    const dialog = await openExport();
    fireEvent.click(within(dialog).getByRole("button", { name: "Export anlegen" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(text);
  });
});
