import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Mark, MarkUpdate, NoteInfo } from "../../api/types";
import { EDITOR_HEADER } from "../../lib/editor";
import { permalinkPath } from "../../lib/research";
import { collections, mailDetail, researchWithTags, tags } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const MAIL = `/api/mails/${mailDetail.id}`;
const SAVED_AT = "2026-10-21T08:00:00Z";

/** The fixture backend plus the research writes about the fixture mail. */
function researchApi(call: ApiCall): unknown {
  const { method, url, body } = call;
  const path = url.pathname;
  if (path === "/api/research") return researchWithTags;
  if (method === "PUT" && path === `${MAIL}/mark`) {
    const update = body as MarkUpdate;
    const mark: Mark = { ...mailDetail.research.mark };
    if (update.review !== undefined) {
      Object.assign(mark, { review: update.review, review_by: "Anna", review_at: SAVED_AT });
    }
    if (update.flagged !== undefined) {
      Object.assign(mark, { flagged: update.flagged, flagged_by: "Anna", flagged_at: SAVED_AT });
    }
    return mark;
  }
  if (method === "POST" && path === "/api/tags") {
    return Response.json({ ...tags[0], ...(body as object), id: 9, mails: 0 }, { status: 201 });
  }
  if (method === "POST" && path === `${MAIL}/tags`) return mailDetail.research.tags;
  if (method === "POST" && path === "/api/collections") {
    return Response.json({ ...collections[0], ...(body as object), id: 5 }, { status: 201 });
  }
  if (method === "POST" && path === `${MAIL}/collections`) return mailDetail.research.collections;
  if (method === "POST" && path === `${MAIL}/notes`) {
    const note: NoteInfo = {
      id: 13,
      body: (body as { body: string }).body,
      author: null,
      created_at: SAVED_AT,
      updated_at: SAVED_AT,
    };
    return Response.json(note, { status: 201 });
  }
  const note = /^\/api\/notes\/(\d+)$/.exec(path);
  if (note && method === "PATCH") {
    const old = mailDetail.research.notes.find((other) => other.id === Number(note[1]))!;
    return { ...old, ...(body as object), updated_at: SAVED_AT };
  }
  if (note && method === "DELETE") return new Response(null, { status: 204 });
  return fixtureApi(call);
}

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method !== "GET");

async function openCard(api = researchApi) {
  const rendered = renderApp(`/mails/${mailDetail.id}`, api);
  const card = (await screen.findByRole("heading", { name: "Recherche" })).closest("section")!;
  return { ...rendered, card };
}

describe("research card", () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("sets the status by click, shows who set it and sends the editor's name", async () => {
    localStorage.setItem("mailrobbe.editor", "Anna Keller");
    const { calls, card } = await openCard();
    const relevant = within(card).getByRole("button", { name: "Relevant" });
    expect(relevant.getAttribute("aria-pressed")).toBe("true");
    expect(within(card).getByText("Lena Vogt · 20.10.2026 16:02")).toBeTruthy();

    fireEvent.click(relevant); // already set: nothing to save
    fireEvent.click(within(card).getByRole("button", { name: "Gesichtet" }));
    expect(await within(card).findByText("Anna · 21.10.2026 10:00")).toBeTruthy();
    expect(
      within(card).getByRole("button", { name: "Gesichtet" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(writes(calls)).toEqual([
      expect.objectContaining({ method: "PUT", body: { review: "seen" } }),
    ]);
    expect(writes(calls)[0].url.pathname).toBe(`${MAIL}/mark`);
    const [, init] = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect((init!.headers as Record<string, string>)[EDITOR_HEADER]).toBe("Anna%20Keller");
    expect(within(card).queryByText("Ohne Namen gespeichert.")).toBeNull();
  });

  it("sets status and bookmark by key, but not while typing", async () => {
    const { calls, card } = await openCard();
    fireEvent.keyDown(window, { key: "r" }); // relevant already
    fireEvent.keyDown(window, { key: "g" });
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(writes(calls)).toHaveLength(2));
    fireEvent.keyDown(window, { key: "u" });
    await waitFor(() => expect(writes(calls)).toHaveLength(3));
    fireEvent.keyDown(window, { key: "m" });
    await waitFor(() => expect(writes(calls)).toHaveLength(4));
    expect(writes(calls).map((call) => call.body)).toEqual([
      { review: "seen" },
      { review: "irrelevant" },
      { review: null },
      { flagged: true },
    ]);
    await waitFor(() =>
      expect(
        within(card).getByRole("button", { name: "Markiert" }).getAttribute("aria-pressed"),
      ).toBe("true"),
    );

    const note = within(card).getByLabelText("Neue Notiz");
    note.focus();
    fireEvent.keyDown(note, { key: "g" });
    fireEvent.keyDown(within(card).getByRole("combobox", { name: "Schlagwort hinzufügen" }), {
      key: "m",
    });
    fireEvent.keyDown(window, { key: "g", ctrlKey: true });
    expect(writes(calls)).toHaveLength(4);
  });

  it("adds a suggested tag, an exact name and a new tag, and removes one", async () => {
    const { calls, card } = await openCard();
    const input = within(card).getByRole("combobox", { name: "Schlagwort hinzufügen" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "gew" } });
    await within(card).findByRole("option", { name: "Gewalt" });
    const options = within(card).getByRole("listbox", { name: "Vorschläge: Schlagwörter" });
    expect(
      within(options)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Gewalt", "„gew“ als neues Schlagwort anlegen"]);
    fireEvent.click(within(options).getByRole("option", { name: "Gewalt" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(input).toHaveProperty("value", "");

    // Enter takes the tag of exactly this name, ignoring case, instead of creating one.
    fireEvent.change(input, { target: { value: "PRÜFEN" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(writes(calls)).toHaveLength(2));

    fireEvent.change(input, { target: { value: "Neues Thema" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(writes(calls)).toHaveLength(4));

    fireEvent.click(
      within(card).getByRole("button", { name: "Schlagwort entfernen: Spendenaffären" }),
    );
    await waitFor(() => expect(writes(calls)).toHaveLength(5));

    expect(writes(calls).map((call) => [call.method, call.url.pathname, call.body])).toEqual([
      ["POST", `${MAIL}/tags`, { add: [3] }],
      ["POST", `${MAIL}/tags`, { add: [7] }],
      // the next colour of the palette: seven tags exist, so the eighth's
      ["POST", "/api/tags", { name: "Neues Thema", color: "gray" }],
      ["POST", `${MAIL}/tags`, { add: [9] }],
      ["POST", `${MAIL}/tags`, { remove: [2] }],
    ]);
  });

  it("says when a new tag's name exists already", async () => {
    const { card } = await openCard((call) =>
      call.method === "POST" && call.url.pathname === "/api/tags"
        ? Response.json(
            { detail: { code: "duplicate_name", message: "tag exists" } },
            { status: 409 },
          )
        : researchApi(call),
    );
    const input = within(card).getByRole("combobox", { name: "Schlagwort hinzufügen" });
    fireEvent.change(input, { target: { value: "Vertrag  Nordstahl" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(
      await within(card).findByText("Diesen Namen gibt es schon, auch in anderer Schreibweise."),
    ).toBeTruthy();
  });

  it("links Akten, creates one and removes one", async () => {
    const { calls, card } = await openCard();
    expect(within(card).getByRole("link", { name: "Story Nordstahl" }).getAttribute("href")).toBe(
      "/akten/1",
    );
    const input = within(card).getByRole("combobox", { name: "Zu Akte hinzufügen" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "spenden" } });
    await within(card).findByRole("option", { name: "Spenden 2024" });
    // The first suggestion is highlighted, not a new Akte of nearly the same name.
    expect(
      within(card).getByRole("option", { name: "Spenden 2024" }).getAttribute("aria-selected"),
    ).toBe("true");
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    fireEvent.change(input, { target: { value: "Vergabe Hafen" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(writes(calls)).toHaveLength(3));
    fireEvent.click(
      within(card).getByRole("button", { name: "Aus Akte entfernen: Story Nordstahl" }),
    );
    await waitFor(() => expect(writes(calls)).toHaveLength(4));
    expect(writes(calls).map((call) => [call.url.pathname, call.body])).toEqual([
      [`${MAIL}/collections`, { add: [2] }],
      ["/api/collections", { name: "Vergabe Hafen" }],
      [`${MAIL}/collections`, { add: [5] }],
      [`${MAIL}/collections`, { remove: [1] }],
    ]);
  });

  it("adds, edits and deletes notes", async () => {
    const { calls, card } = await openCard();
    const notes = within(card).getByRole("list", { name: "Notizen" });
    const [first, second] = within(notes).getAllByRole("listitem");
    expect(within(first).getByText("Lena Vogt · 20.10.2026 16:05")).toBeTruthy();
    expect(
      within(second).getByText("ohne Namen · 21.10.2026 09:40 · bearbeitet 21.10.2026 09:52"),
    ).toBeTruthy();

    const draft = within(card).getByLabelText("Neue Notiz");
    fireEvent.change(draft, { target: { value: "  Quelle prüfen  " } });
    fireEvent.keyDown(draft, { key: "Enter", ctrlKey: true });
    expect(await within(card).findByText("Quelle prüfen")).toBeTruthy();
    expect(draft).toHaveProperty("value", "");

    fireEvent.click(within(first).getByRole("button", { name: "Bearbeiten" }));
    const edit = within(card).getByLabelText("Notiz bearbeiten");
    fireEvent.change(edit, { target: { value: "Anlage fehlt weiterhin." } });
    fireEvent.click(within(card).getByRole("button", { name: "Speichern" }));
    expect(await within(card).findByText("Anlage fehlt weiterhin.")).toBeTruthy();

    fireEvent.click(within(second).getByRole("button", { name: "Löschen" }));
    expect(writes(calls)).toHaveLength(2); // asks first
    fireEvent.click(within(second).getByRole("button", { name: "Endgültig löschen" }));
    await waitFor(() => expect(within(card).queryByText(/Anlage liegt in Mail 184133/)).toBeNull());

    expect(writes(calls).map((call) => [call.method, call.url.pathname, call.body])).toEqual([
      ["POST", `${MAIL}/notes`, { body: "Quelle prüfen" }],
      ["PATCH", "/api/notes/11", { body: "Anlage fehlt weiterhin." }],
      ["DELETE", "/api/notes/12", undefined],
    ]);
  });

  it("copies the permalink and shows its path", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { card } = await openCard();
    const path = permalinkPath(mailDetail.raw_sha256);
    expect(path).toMatch(/^\/m\/[0-9a-f]{16}$/);
    expect(within(card).getByText(path)).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Link kopieren" }));
    expect(await within(card).findByText("Link kopiert.")).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}${path}`);
  });

  it("says that byte-identical copies share the research data", async () => {
    const { card } = await openCard((call) =>
      call.method === "GET" && call.url.pathname === MAIL
        ? { ...mailDetail, duplicates: [184300, 184301] }
        : researchApi(call),
    );
    expect(
      within(card).getByText(
        "Status, Schlagwörter, Akten und Notizen gelten auch für die 2 byte-identischen Kopien dieser Mail.",
      ),
    ).toBeTruthy();
  });

  it("saves without a name and then offers to enter one", async () => {
    const { calls, card } = await openCard();
    fireEvent.click(within(card).getByRole("button", { name: "Markiert" }));
    expect(await within(card).findByText("Ohne Namen gespeichert.")).toBeTruthy();
    const [, init] = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(init!.headers).not.toHaveProperty(EDITOR_HEADER);

    fireEvent.click(within(card).getByRole("button", { name: "Namen eintragen" }));
    const dialog = screen.getByRole("dialog", { name: "Name für Notizen und Änderungen" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Lena" } });
    // Keys in the dialog belong to it, also on its buttons.
    fireEvent.keyDown(within(dialog).getByRole("button", { name: "Abbrechen" }), { key: "n" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(within(card).queryByText("Ohne Namen gespeichert.")).toBeNull());
    expect(screen.getByRole("button", { name: "Bearbeitet als Lena" })).toBeTruthy();

    fireEvent.keyDown(window, { key: "g" });
    await waitFor(() => expect(writes(calls)).toHaveLength(2));
    expect(writes(calls).map((call) => call.body)).toEqual([{ flagged: true }, { review: "seen" }]);
    const [, named] = vi.mocked(fetch).mock.calls.filter(([, init]) => init?.method === "PUT")[1];
    expect((named!.headers as Record<string, string>)[EDITOR_HEADER]).toBe("Lena");
  });

  it("offers the PDF next to the EML download", async () => {
    await openCard();
    const actions = screen.getByRole("heading", { name: "Aktionen" }).closest("section")!;
    expect(
      within(actions)
        .getAllByRole("link")
        .slice(0, 3)
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Als EML herunterladen", `${MAIL}/eml`],
      ["Als PDF herunterladen", `${MAIL}/pdf`],
      ["PDF mit Notizen", `${MAIL}/pdf?research=true`],
    ]);
  });
});
