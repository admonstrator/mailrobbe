import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ExportInfo } from "../../api/types";
import { collections, exports, research, searches, tags } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The fixture backend, answering the research writes as the API would. */
function researchApi(call: ApiCall): unknown {
  const { method, url, body } = call;
  const path = url.pathname;
  const id = Number(path.split("/").pop());
  if (method === "DELETE") return new Response(null, { status: 204 });
  if (method === "POST" && path === "/api/collections") {
    return Response.json(
      { ...collections[0], ...(body as object), id: 5, mails: 0 },
      { status: 201 },
    );
  }
  if (method === "POST" && path === "/api/tags") {
    return Response.json({ ...tags[0], ...(body as object), id: 9, mails: 0 }, { status: 201 });
  }
  if (method === "PATCH" && path.startsWith("/api/tags/")) {
    return { ...tags.find((tag) => tag.id === id), ...(body as object) };
  }
  if (method === "PATCH" && path.startsWith("/api/searches/")) {
    return { ...searches.find((search) => search.id === id), ...(body as object) };
  }
  return fixtureApi(call);
}

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method !== "GET");
const tab = (name: string | RegExp) => screen.findByRole("tab", { name });

describe("Akten screen", () => {
  it("shows the Akten with counts in the tabs", async () => {
    renderApp("/akten");
    const link = await screen.findByRole("link", { name: "Story Nordstahl" });
    expect(link.getAttribute("href")).toBe("/akten/1");
    expect(screen.getByRole("heading", { level: 1, name: "Akten" })).toBeTruthy();
    expect(document.title).toBe("Akten · Mailrobbe");
    const row = link.closest("li")!;
    expect(within(row).getByText(collections[0].description)).toBeTruthy();
    expect(within(row).getByText("24 Mails")).toBeTruthy();
    expect(within(row).getByText(/angelegt von Lena Vogt/)).toBeTruthy();
    expect(screen.getByText("61 relevant · 9 markiert · 690 gesichtet")).toBeTruthy();
    for (const name of [
      "Akten 1",
      "Themen",
      "Gespeicherte Suchen 2",
      "Schlagworte 2",
      "Notizen 23",
      "Exporte",
    ]) {
      expect(screen.getByRole("tab", { name })).toBeTruthy();
    }
    expect(screen.getByRole("tab", { name: "Akten 1" }).getAttribute("aria-selected")).toBe("true");
  });

  it("keeps the tab in the URL", async () => {
    const { router } = renderApp("/akten");
    fireEvent.click(await tab("Schlagworte 2"));
    expect(router.state.location.search).toBe("?tab=schlagworte");
    expect(await screen.findByText("Spendenaffären")).toBeTruthy();
    expect(document.title).toBe("Schlagworte · Akten · Mailrobbe");
    fireEvent.click(screen.getByRole("tab", { name: "Akten 1" }));
    expect(router.state.location.search).toBe("");
  });

  it("creates an Akte and opens it", async () => {
    const { router, calls } = renderApp("/akten", researchApi);
    fireEvent.click(await screen.findByRole("button", { name: "Neue Akte" }));
    const dialog = screen.getByRole("dialog", { name: "Neue Akte" });
    const create = within(dialog).getByRole("button", { name: "Akte anlegen" });
    expect((create as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), {
      target: { value: "  Story Hafen " },
    });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Beschreibung (optional)" }), {
      target: { value: "Pacht am Kai 4" },
    });
    fireEvent.click(create);
    await waitFor(() => expect(router.state.location.pathname).toBe("/akten/5"));
    expect(writes(calls)).toEqual([
      expect.objectContaining({
        method: "POST",
        body: { name: "Story Hafen", description: "Pacht am Kai 4" },
      }),
    ]);
  });
});

describe("Themen tab", () => {
  it("shows the themes with searches and word fields", async () => {
    renderApp("/akten?tab=themen");
    const theme = (await screen.findByRole("heading", { name: "Spendenaffären" })).closest(
      "section",
    )!;
    expect(within(theme).getByText("Spenden, Finanzierung und Geldflüsse.")).toBeTruthy();
    const search = within(theme).getByRole("link", {
      name: "Spendenaffären: Bargeld, Stückelung, Strohleute",
    });
    expect(search.getAttribute("href")).toBe("/mails?q=Barspende+or+Barzahlung+or+Bargeld");
    const words = within(theme).getByRole("list", { name: "Wortfeld Spendenaffären" });
    expect(within(words).getByRole("link", { name: "Barspende" }).getAttribute("href")).toBe(
      "/mails?q=Barspende",
    );
    expect(within(words).getByRole("link", { name: "in bar" }).getAttribute("href")).toBe(
      "/mails?q=%22in+bar%22",
    );
    expect(screen.getByRole("heading", { name: "Gewalt" })).toBeTruthy();
  });

  it("offers the starter set while something is missing", async () => {
    let created = false;
    const { calls } = renderApp("/akten?tab=themen", (call) => {
      if (call.url.pathname === "/api/research/starter") created = true;
      if (call.url.pathname === "/api/research" && created) {
        return { ...research, starter_missing: 0 };
      }
      return fixtureApi(call);
    });
    const button = await screen.findByRole("button", { name: "Themen-Startset anlegen" });
    expect(screen.getByText(/22 fehlen noch/)).toBeTruthy();
    fireEvent.click(button);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Themen-Startset anlegen" })).toBeNull(),
    );
    expect(writes(calls).map((call) => [call.method, call.url.pathname])).toEqual([
      ["POST", "/api/research/starter"],
    ]);
  });

  it("does not offer it when nothing is missing", async () => {
    renderApp("/akten?tab=themen", (call) =>
      call.url.pathname === "/api/research"
        ? { ...research, starter_missing: 0 }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Gewalt" });
    expect(screen.queryByRole("button", { name: "Themen-Startset anlegen" })).toBeNull();
  });
});

describe("Gespeicherte Suchen tab", () => {
  it("lists the searches with their Akte and counts their matches", async () => {
    const { calls } = renderApp("/akten?tab=suchen");
    const link = await screen.findByRole("link", { name: "Nordstahl an Einkauf" });
    expect(link.getAttribute("href")).toBe("/mails?q=from%3Anordstahl&sort=date_asc");
    const row = link.closest("li")!;
    expect(within(row).getByText(/gespeichert von Lena Vogt/)).toBeTruthy();
    const akte = within(row).getByRole("combobox", { name: "Akte von „Nordstahl an Einkauf“" });
    expect((akte as HTMLSelectElement).value).toBe("1");
    expect(await within(row).findByText(/1\.207 Treffer/)).toBeTruthy();
    const counted = calls.filter((call) => call.url.pathname === "/api/mails/summary");
    expect(counted.map((call) => call.url.searchParams.get("q")).sort()).toEqual([
      "Barspende or Barzahlung or Bargeld",
      "from:nordstahl",
    ]);
  });

  it("counts a search with its search options and opens it with them (D178)", async () => {
    const query = "q=Neger&scope=subject&scope=body&whole_word=true&min_hits=2";
    const saved = { ...searches[0], id: 5, name: "Neger ohne Dateinamen", query };
    const { calls } = renderApp("/akten?tab=suchen", (call) =>
      call.url.pathname === "/api/research"
        ? { ...research, searches: [...research.searches, saved] }
        : fixtureApi(call),
    );
    const link = await screen.findByRole("link", { name: "Neger ohne Dateinamen" });
    expect(link.getAttribute("href")).toBe(`/mails?${query}`);
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.url.pathname === "/api/mails/summary" && call.url.search === `?${query}`,
        ),
      ).toBe(true),
    );
  });

  it("renames, reassigns and deletes a search", async () => {
    const { calls } = renderApp("/akten?tab=suchen", researchApi);
    fireEvent.click(
      await screen.findByRole("button", { name: "Name von „Nordstahl an Einkauf“ bearbeiten" }),
    );
    const field = screen.getByRole("textbox", { name: "Name von „Nordstahl an Einkauf“" });
    fireEvent.change(field, { target: { value: "Nordstahl an die Einkaufsleitung" } });
    fireEvent.submit(field);
    await waitFor(() => expect(writes(calls)).toHaveLength(1));

    fireEvent.change(screen.getByRole("combobox", { name: "Akte von „Nordstahl an Einkauf“" }), {
      target: { value: "" },
    });
    await waitFor(() => expect(writes(calls)).toHaveLength(2));

    fireEvent.click(
      screen.getByRole("button", {
        name: "„Spendenaffären: Bargeld, Stückelung, Strohleute“ löschen",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Suche löschen" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Löschen" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(3));
    expect(writes(calls).map((call) => [call.method, call.url.pathname, call.body])).toEqual([
      ["PATCH", "/api/searches/4", { name: "Nordstahl an die Einkaufsleitung" }],
      ["PATCH", "/api/searches/4", { collection_id: null }],
      ["DELETE", "/api/searches/3", undefined],
    ]);
  });
});

describe("Schlagworte tab", () => {
  it("lists the tags with description and mail count", async () => {
    renderApp("/akten?tab=schlagworte");
    const row = (await screen.findByText("Spendenaffären")).closest("li")!;
    expect(within(row).getByText("Spenden, Finanzierung und Geldflüsse.")).toBeTruthy();
    expect(within(row).getByRole("link", { name: "37 Mails" }).getAttribute("href")).toBe(
      "/mails?tag=2",
    );
  });

  it("creates, edits and deletes tags", async () => {
    const { calls } = renderApp("/akten?tab=schlagworte", researchApi);
    fireEvent.click(await screen.findByRole("button", { name: "Neues Schlagwort" }));
    let dialog = screen.getByRole("dialog", { name: "Neues Schlagwort" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), {
      target: { value: "Hafen" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Schlagwort anlegen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "„Vertrag Nordstahl“ bearbeiten" }));
    dialog = screen.getByRole("dialog", { name: "Schlagwort bearbeiten" });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(8);
    fireEvent.click(within(dialog).getByRole("radio", { name: "Rot" }));
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Beschreibung (optional)" }), {
      target: { value: "Rahmenvertrag 2026" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "„Spendenaffären“ löschen" }));
    dialog = screen.getByRole("dialog", { name: "Schlagwort löschen" });
    expect(dialog.textContent).toContain(
      "Das Schlagwort „Spendenaffären“ wird gelöscht und von 37 Mails entfernt.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Löschen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    expect(writes(calls).map((call) => [call.method, call.url.pathname, call.body])).toEqual([
      ["POST", "/api/tags", { name: "Hafen", color: "blue", description: "" }],
      ["PATCH", "/api/tags/1", { color: "red", description: "Rahmenvertrag 2026" }],
      ["DELETE", "/api/tags/2", undefined],
    ]);
  });
});

describe("Notizen tab", () => {
  it("lists the notes with author and mail", async () => {
    renderApp("/akten?tab=notizen");
    const note = (await screen.findByText("Absender taucht nach März nicht mehr auf.")).closest(
      "li",
    )!;
    expect(within(note).getByText(/Jan Brehm/)).toBeTruthy();
    expect(within(note).getByText("Mail nicht mehr im Archiv")).toBeTruthy();
    expect(screen.getByText("2 Notizen")).toBeTruthy();
    const linked = screen.getAllByRole("listitem")[0];
    expect(within(linked).getByRole("link").getAttribute("href")).toBe("/mails/184221");
  });

  it("searches the note texts", async () => {
    const { calls } = renderApp("/akten?tab=notizen");
    await screen.findByText("Absender taucht nach März nicht mehr auf.");
    fireEvent.change(screen.getByRole("searchbox", { name: "Notizen durchsuchen" }), {
      target: { value: " März " },
    });
    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.url.pathname === "/api/notes" && call.url.searchParams.get("q") === "März",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("2 Notizen gefunden")).toBeTruthy();
  });
});

describe("Exporte tab", () => {
  it("shows each export with its recorded SHA-256 and download", async () => {
    const pending: ExportInfo = {
      ...exports[0],
      id: 4,
      label: "",
      include_research: true,
      manifest_sha256: null,
      downloaded_at: null,
      download_url: "/api/exports/4/download",
    };
    renderApp("/akten?tab=exporte", (call) =>
      call.url.pathname === "/api/exports" ? [pending, ...exports] : fixtureApi(call),
    );
    const done = (await screen.findByText("Story Nordstahl")).closest("li")!;
    expect(within(done).getByText("ohne Rechercheangaben")).toBeTruthy();
    expect(within(done).getByText(/Export 3 · 24 Mails/)).toBeTruthy();
    const hash = within(done).getByText("4f1c9a0e4f1c…");
    expect(hash.getAttribute("title")).toBe(exports[0].manifest_sha256);
    expect(within(done).getByRole("link", { name: "ZIP herunterladen" }).getAttribute("href")).toBe(
      "/api/exports/3/download",
    );
    const open = screen.getByText("Export 4").closest("li")!;
    expect(within(open).getByText("mit Rechercheangaben")).toBeTruthy();
    expect(within(open).getByText("noch nicht heruntergeladen")).toBeTruthy();
  });
});
