import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { HideRuleFields, HideRuleInfo, HideRulePreview, MailDetail } from "../../api/types";
import { mailDetail, mailItems, summaryAll } from "../../test/fixtures";
import { fixtureApi, renderApp, renderElement, type ApiCall } from "../../test/render";
import { subjectStart } from "./labels";
import { RuleDialog } from "./RuleDialog";

const rule: HideRuleInfo = {
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
  updated_by: "Anna Müller",
  updated_at: "2026-10-20T09:00:00Z",
};

const preview: HideRulePreview = {
  mails: 1234,
  kept: 12,
  with_terms: 3,
  examples: mailItems.slice(0, 5),
};

function api(detail: MailDetail = mailDetail, hidden: number | null = null) {
  return (call: ApiCall): unknown => {
    const { method, url } = call;
    if (url.pathname === "/api/hide-rules/preview") return preview;
    if (url.pathname === "/api/hide-rules" && method === "POST") {
      return Response.json({ ...rule, ...(call.body as HideRuleFields) }, { status: 201 });
    }
    if (method === "GET" && url.pathname === `/api/mails/${detail.id}`) return detail;
    if (url.pathname === "/api/mails/summary" && !url.searchParams.has("include_hidden")) {
      return { ...summaryAll, hidden };
    }
    return fixtureApi(call);
  };
}

const previews = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/hide-rules/preview");

describe("rule dialog", () => {
  it("opens empty from the search menu and saves only with a criterion", async () => {
    const { calls } = renderApp("/mails", api());
    fireEvent.click(await screen.findByRole("button", { name: "Suchmenü" }));
    fireEvent.click(screen.getByRole("button", { name: "Regel anlegen" }));
    const dialog = screen.getByRole("dialog", { name: "Ausblendregel anlegen" });
    expect(screen.queryByRole("dialog", { name: "Suchmenü" })).toBeNull();
    for (const label of ["Name (optional)", "Absenderadresse", "Domain", "Verteiler (List-Id)"]) {
      expect(within(dialog).getByLabelText(label)).toHaveProperty("value", "");
    }
    expect(within(dialog).getByRole("button", { name: "Speichern" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(within(dialog).getByText(/Sobald eine Angabe ausgefüllt ist/)).toBeTruthy();
    expect(previews(calls)).toHaveLength(0);
  });

  it("previews the criteria last typed and saves the rule", async () => {
    const { calls } = renderElement(<RuleDialog draft={{}} onClose={() => undefined} />, api());
    const dialog = screen.getByRole("dialog", { name: "Ausblendregel anlegen" });
    const save = within(dialog).getByRole("button", { name: "Speichern" });

    // A name alone is no criterion; typed quickly, only the criteria that rest are asked for.
    fireEvent.change(within(dialog).getByLabelText("Name (optional)"), {
      target: { value: "Rundbrief" },
    });
    expect(save).toHaveProperty("disabled", true);
    const list = within(dialog).getByLabelText("Verteiler (List-Id)");
    fireEvent.change(list, { target: { value: "news" } });
    fireEvent.change(list, { target: { value: " news.verein.example " } });
    expect(save).toHaveProperty("disabled", false);
    await within(dialog).findByText("1.234 Mails");
    expect(previews(calls)).toHaveLength(1);
    expect(previews(calls)[0].body).toEqual({
      sender: null,
      person_id: null,
      domain: null,
      list_id: "news.verein.example",
      automated: false,
      subject: null,
      subject_match: "contains",
    });
    const figures = within(dialog).getByRole("region", { name: "Vorschau" });
    expect(figures.textContent).toContain(
      "1.234 Mails passen, 12 davon bleiben sichtbar (Akte, Notiz, Lesezeichen oder „relevant“).",
    );
    expect(figures.textContent).toContain("3 enthalten Begriffe aus den Themenfeldern");
    const examples = within(figures).getAllByRole("link");
    expect(examples).toHaveLength(5);
    expect(examples[0].getAttribute("href")).toBe(`/mails/${mailItems[0].id}`);
    expect(examples[0].getAttribute("target")).toBe("_blank");
    expect(examples[0].textContent).toContain(mailItems[0].subject ?? "");

    // the subject: starts with, in any case
    fireEvent.change(within(dialog).getByLabelText("Vergleich des Betreffs"), {
      target: { value: "starts" },
    });
    fireEvent.change(within(dialog).getByLabelText("Betreff"), {
      target: { value: "Wochenrückblick" },
    });
    await waitFor(() => expect(previews(calls)).toHaveLength(2));
    expect(previews(calls)[1].body).toMatchObject({
      subject: "Wochenrückblick",
      subject_match: "starts",
    });

    fireEvent.click(save);
    const saved = await screen.findByRole("dialog", { name: "Ausblendregel gespeichert" });
    const post = calls.find(
      (call) => call.method === "POST" && call.url.pathname === "/api/hide-rules",
    )!;
    expect(post.body).toMatchObject({
      name: "Rundbrief",
      list_id: "news.verein.example",
      subject: "Wochenrückblick",
    });
    expect(saved.textContent).toContain("„Rundbrief“ passt auf 1.234 Mails.");
    expect(
      within(saved).getByRole("link", { name: "Zu den Ausblendregeln" }).getAttribute("href"),
    ).toBe("/ausgeblendet");
  });

  it("shows on a hidden mail which rules hide it and why it stays visible", async () => {
    const hidden = { ...mailDetail, hidden: { rules: [rule], kept: true } };
    renderApp(`/mails/${mailDetail.id}`, api(hidden));
    const note = await screen.findByRole("region", { name: "Ausgeblendet" });
    expect(note.textContent).toBe(
      "Ausgeblendet durch die Regel „Verteiler newsletter.example · Betreff beginnt mit „Wochenrückblick““. Sie bleibt trotzdem in Liste und Suche, weil sie in der Akte „Story Nordstahl“ liegt, Notizen hat und als „relevant“ markiert ist.",
    );
    expect(within(note).getByRole("link").getAttribute("href")).toBe("/ausgeblendet");
  });

  it("says that a hidden mail without research data is left out", async () => {
    const research = {
      mark: { ...mailDetail.research.mark, review: null },
      tags: [],
      collections: [],
      notes: [],
    };
    const hidden = { ...mailDetail, research, hidden: { rules: [rule], kept: false } };
    renderApp(`/mails/${mailDetail.id}`, api(hidden));
    const note = await screen.findByRole("region", { name: "Ausgeblendet" });
    expect(note.textContent).toContain("Sie fehlt deshalb in Liste und Suche");
  });

  it("shows no note on a mail no rule hides", async () => {
    renderApp(`/mails/${mailDetail.id}`, api());
    await screen.findByRole("button", { name: "Mails wie diese ausblenden" });
    expect(screen.queryByRole("region", { name: "Ausgeblendet" })).toBeNull();
  });

  it("offers a rule for mails like the one shown", async () => {
    const { calls } = renderApp(
      `/mails/${mailDetail.id}`,
      api({
        ...mailDetail,
        subject: "AW: Re: Wochenrückblick 12",
        list_id: "news.nordlicht.example",
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Mails wie diese ausblenden" }));
    const dialog = screen.getByRole("dialog", { name: "Ausblendregel anlegen" });
    expect(within(dialog).getByRole("radio", { name: "Adresse" })).toHaveProperty("checked", true);
    expect(
      within(dialog).getByRole("radio", { name: "Anna Keller mit allen Adressen" }),
    ).toBeTruthy();
    expect(within(dialog).getByLabelText("Absenderadresse")).toHaveProperty(
      "value",
      "anna.keller@nordlicht-gmbh.example",
    );
    expect(within(dialog).getByLabelText("Verteiler (List-Id)")).toHaveProperty(
      "value",
      "news.nordlicht.example",
    );
    expect(within(dialog).getByLabelText("Betreff")).toHaveProperty("value", "Wochenrückblick");
    expect(within(dialog).getByLabelText("Vergleich des Betreffs")).toHaveProperty(
      "value",
      "starts",
    );
    await waitFor(() => expect(previews(calls)).toHaveLength(1));

    // the person instead of the address
    fireEvent.click(within(dialog).getByRole("radio", { name: "Anna Keller mit allen Adressen" }));
    expect(within(dialog).queryByLabelText("Absenderadresse")).toBeNull();
    await waitFor(() => expect(previews(calls)).toHaveLength(2));
    expect(previews(calls)[1].body).toMatchObject({ sender: null, person_id: 11 });
  });
});

describe("hidden mails in the list", () => {
  it("names how many are hidden and shows them on a click", async () => {
    const { router } = renderApp("/mails", api(mailDetail, 1234));
    const show = await screen.findByRole("button", { name: "zeigen" });
    expect(show.parentElement?.textContent).toBe("1.234 ausgeblendet · zeigen");
    fireEvent.click(show);
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).get("include_hidden")).toBe("true"),
    );
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Mit ausgeblendeten Mails" }),
    ).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("button", { name: "zeigen" })).toBeNull());
  });

  it("says nothing while no mail is hidden", async () => {
    renderApp("/mails", api(mailDetail, 0));
    await screen.findAllByRole("row");
    expect(screen.queryByText(/ausgeblendet ·/)).toBeNull();
  });
});

describe("subjectStart", () => {
  it.each([
    ["Re: AW: Wochenrückblick 12", "Wochenrückblick"],
    ["WG: Fwd: Einladung zur Sitzung", "Einladung zur Sitzung"],
    ["FW[2]: Spende – Quittung 2024-03", "Spende – Quittung"],
    ["[Newsletter] Ausgabe 5", "[Newsletter] Ausgabe"],
    ["2024: Jahresbericht", "2024: Jahresbericht"],
    [null, ""],
  ])("%s gives %s", (subject, start) => {
    expect(subjectStart(subject)).toBe(start);
  });
});
