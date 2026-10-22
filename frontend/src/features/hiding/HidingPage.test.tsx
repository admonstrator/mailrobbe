import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HideRuleInfo, HideRuleList, HideRulePreview, HideSuggestion } from "../../api/types";
import { mailItems } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const weekly: HideRuleInfo = {
  id: 3,
  name: null,
  sender: null,
  person_id: null,
  domain: null,
  list_id: "newsletter.example",
  automated: false,
  subject: "Wochenrückblick",
  subject_match: "starts",
  enabled: true,
  person: null,
  mails: 1234,
  computed_at: "2026-10-22T08:00:00Z",
  created_by: "Anna Müller",
  created_at: "2026-10-20T09:00:00Z",
  updated_by: "Bert",
  updated_at: "2026-10-21T10:00:00Z",
};

const system: HideRuleInfo = {
  ...weekly,
  id: 2,
  name: "Systemmails",
  list_id: null,
  automated: true,
  subject: null,
  subject_match: "contains",
  enabled: false,
  mails: 0,
  created_by: null,
  updated_by: null,
  updated_at: weekly.created_at,
};

const rules: HideRuleList = { rules: [weekly, system], hidden: 1200, kept: 34 };

const newsletter = { person_id: 77, email: "info@verein.example", name: "Newsletter Verein" };
const suggestions: HideSuggestion[] = [
  { kind: "list", list_id: "news.verein.example", person: null, mails: 512 },
  { kind: "sender", list_id: null, person: newsletter, mails: 300 },
];

const preview: HideRulePreview = {
  mails: 512,
  kept: 2,
  with_terms: 0,
  examples: mailItems.slice(0, 5),
};

function api(list: HideRuleList = rules) {
  return (call: ApiCall): unknown => {
    const { method, url } = call;
    if (url.pathname === "/api/hide-rules" && method === "GET") return list;
    if (url.pathname === "/api/hide-rules/suggestions") return suggestions;
    if (url.pathname === "/api/hide-rules/preview") return preview;
    if (url.pathname === "/api/hide-rules" && method === "POST") {
      return Response.json({ ...weekly, id: 9, ...(call.body as object) }, { status: 201 });
    }
    if (/^\/api\/hide-rules\/\d+$/.test(url.pathname)) {
      if (method === "DELETE") return new Response(null, { status: 204 });
      return { ...weekly, ...(call.body as object) };
    }
    return fixtureApi(call);
  };
}

const writes = (calls: ApiCall[], method: string) =>
  calls.filter((call) => call.method === method && call.url.pathname.startsWith("/api/hide-rules"));

const DESCRIPTION = "Verteiler newsletter.example · Betreff beginnt mit „Wochenrückblick“";

describe("hide rules page", () => {
  it("lists the rules with their criteria, mails, makers and the totals", async () => {
    renderApp("/ausgeblendet", api());
    const list = await screen.findByRole("list", { name: "Ausblendregeln" });
    const [first, second] = within(list).getAllByRole("listitem");
    expect(within(first).getByText(DESCRIPTION)).toBeTruthy();
    expect(within(first).getByText("1.234 Mails")).toBeTruthy();
    expect(
      within(first).getByText(
        "angelegt von Anna Müller am 20.10.2026 · geändert von Bert am 21.10.2026",
      ),
    ).toBeTruthy();
    expect(within(first).getByRole("switch", { name: `„${DESCRIPTION}“ aktiv` })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(second).getByText("Systemmails")).toBeTruthy();
    expect(within(second).getByText("automatisch versendet")).toBeTruthy();
    expect(within(second).getByText("ausgeschaltet")).toBeTruthy();
    expect(within(second).getByText("angelegt am 20.10.2026")).toBeTruthy();
    expect(screen.getByText(/Mails sind ausgeblendet/).textContent).toBe(
      "1.200 Mails sind ausgeblendet, 34 weitere passen, bleiben aber sichtbar (Akte, Notiz, Lesezeichen oder „relevant“). Liste mit ausgeblendeten Mails",
    );
    expect(
      screen.getByRole("link", { name: "Liste mit ausgeblendeten Mails" }).getAttribute("href"),
    ).toBe("/mails?include_hidden=true");
  });

  it("switches a rule off with all its criteria", async () => {
    const { calls } = renderApp("/ausgeblendet", api());
    fireEvent.click(await screen.findByRole("switch", { name: `„${DESCRIPTION}“ aktiv` }));
    await waitFor(() => expect(writes(calls, "PUT")).toHaveLength(1));
    const [put] = writes(calls, "PUT");
    expect(put.url.pathname).toBe("/api/hide-rules/3");
    expect(put.body).toEqual({
      name: null,
      sender: null,
      person_id: null,
      domain: null,
      list_id: "newsletter.example",
      automated: false,
      subject: "Wochenrückblick",
      subject_match: "starts",
      enabled: false,
    });
  });

  it("deletes a rule only after asking in the page", async () => {
    const { calls } = renderApp("/ausgeblendet", api());
    fireEvent.click(await screen.findByRole("button", { name: `„${DESCRIPTION}“ löschen` }));
    const dialog = screen.getByRole("dialog", { name: "Ausblendregel löschen" });
    expect(dialog.textContent).toContain(
      "Ihre 1.234 Mails erscheinen sofort wieder in Liste und Suche",
    );
    expect(writes(calls, "DELETE")).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Löschen" }));
    await waitFor(() => expect(writes(calls, "DELETE")).toHaveLength(1));
    expect(writes(calls, "DELETE")[0].url.pathname).toBe("/api/hide-rules/3");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("edits a rule and keeps whether it is enabled", async () => {
    const { calls } = renderApp("/ausgeblendet", api());
    fireEvent.click(await screen.findByRole("button", { name: "„Systemmails“ bearbeiten" }));
    const dialog = screen.getByRole("dialog", { name: "Ausblendregel bearbeiten" });
    expect(within(dialog).getByLabelText("Name (optional)")).toHaveProperty("value", "Systemmails");
    expect(within(dialog).getByRole("checkbox", { name: /automatisch versendet/ })).toHaveProperty(
      "checked",
      true,
    );
    fireEvent.change(within(dialog).getByLabelText("Domain"), {
      target: { value: "system.example" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(writes(calls, "PUT")).toHaveLength(1));
    expect(writes(calls, "PUT")[0].body).toMatchObject({
      name: "Systemmails",
      domain: "system.example",
      automated: true,
      enabled: false,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("opens the dialog filled with a suggestion", async () => {
    const { calls } = renderApp("/ausgeblendet", api());
    const side = await screen.findByRole("complementary", { name: "Vorschläge" });
    expect(await within(side).findByText("Verteiler · 512 Mails")).toBeTruthy();
    expect(within(side).getByText("Absender info@verein.example · 300 Mails")).toBeTruthy();

    fireEvent.click(
      within(side).getByRole("button", { name: "Regel für news.verein.example anlegen" }),
    );
    let dialog = screen.getByRole("dialog", { name: "Ausblendregel anlegen" });
    expect(within(dialog).getByLabelText("Verteiler (List-Id)")).toHaveProperty(
      "value",
      "news.verein.example",
    );
    await within(dialog).findByText("512 Mails");
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));

    fireEvent.click(
      within(side).getByRole("button", { name: "Regel für Newsletter Verein anlegen" }),
    );
    dialog = screen.getByRole("dialog", { name: "Ausblendregel anlegen" });
    expect(
      within(dialog).getByRole("radio", { name: "Newsletter Verein mit allen Adressen" }),
    ).toHaveProperty("checked", true);
    expect(within(dialog).queryByLabelText("Absenderadresse")).toBeNull();
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/hide-rules/preview" &&
            (call.body as { person_id?: number }).person_id === 77,
        ),
      ).toBe(true),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    const created = () =>
      writes(calls, "POST").filter((call) => call.url.pathname === "/api/hide-rules");
    await waitFor(() => expect(created()).toHaveLength(1));
    expect(created()[0].body).toMatchObject({ person_id: 77, sender: null });
    // on the rules' page the dialog closes once the rule is saved
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("explains what rules are for while there is none", async () => {
    renderApp("/ausgeblendet", api({ rules: [], hidden: 0, kept: 0 }));
    expect(await screen.findByText("Noch keine Ausblendregel")).toBeTruthy();
    expect(screen.getByText(/blendet Mails aus, die bei der Recherche nur stören/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Erste Regel anlegen" }));
    expect(screen.getByRole("dialog", { name: "Ausblendregel anlegen" })).toBeTruthy();
  });
});
