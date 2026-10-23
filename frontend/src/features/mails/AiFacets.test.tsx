import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiFacets, AiTagAdopt } from "../../api/types";
import {
  aiFacets,
  aiFacetsEmpty,
  aiFacetsFiltered,
  summaryFiltered,
  tags as teamTags,
} from "../../test/fixtures";
import { openInsights } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The fixture backend with the AI facets (filtered ones whenever a filter is given), the tag
 *  lookup by id, the adoption, and the summary of a list narrowed to one AI tag (38 mails). */
function aiApi(unfiltered: AiFacets = aiFacets) {
  return (call: ApiCall): unknown => {
    const { pathname, searchParams } = call.url;
    if (pathname === "/api/ai/facets") return searchParams.size ? aiFacetsFiltered : unfiltered;
    if (pathname === "/api/ai/tags") {
      const ids = searchParams.getAll("id").map(Number);
      return aiFacets.tags.filter((tag) => ids.includes(tag.id));
    }
    if (pathname === "/api/ai/tags/12/adopt") return { tag_id: 9, created: true, mails: 214 };
    if (pathname === "/api/ai/tags/31/adopt") return { tag_id: 1, created: false, mails: 7 };
    if (pathname === "/api/mails/summary" && searchParams.has("ai_tag")) {
      return { ...summaryFiltered, total: 38 };
    }
    return fixtureApi(call);
  };
}

const facetCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/ai/facets");
const adoptCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname.endsWith("/adopt"));

/** A panel of the AI facets in the panel "Einblicke", which this opens. */
async function panel(name: string): Promise<HTMLElement> {
  const insights = await openInsights();
  const heading = await within(insights).findByRole("heading", { name, level: 2 });
  return heading.closest("section")!;
}

const chipTexts = (section: HTMLElement) =>
  within(section)
    .getAllByRole("button", { pressed: false })
    .map((chip) => chip.textContent);

describe("AI facets in the panel Einblicke", () => {
  it("show the AI tags and themes of every mail, marked machine made", async () => {
    const { calls } = renderApp("/mails", aiApi());
    const tagsPanel = await panel("KI-Schlagwörter");
    const themesPanel = await panel("KI-Themen");
    expect(chipTexts(tagsPanel)).toEqual([
      "Spende 214",
      "Parteitag 96",
      "Vorstandssitzung 41",
      "Barzahlung 17",
    ]);
    expect(chipTexts(themesPanel)).toEqual(["Spendenaffären 58", "Gewalt 6"]);
    for (const section of [tagsPanel, themesPanel]) {
      expect(within(section).getByText("maschinell erzeugt")).toBeTruthy();
      expect(within(section).getByText("in allen Mails")).toBeTruthy();
    }
    expect(
      within(tagsPanel).getByRole("button", { name: "„Spende“ als Team-Tag übernehmen" }),
    ).toBeTruthy();
    // One request with the list's filters (none), beside the list's own.
    expect(facetCalls(calls).map((call) => call.url.search)).toEqual([""]);
  });

  it("narrow the list with a click, name the filter in a chip, and widen it again", async () => {
    const { router, calls } = renderApp("/mails", aiApi());
    fireEvent.click(
      within(await panel("KI-Schlagwörter")).getByRole("button", { name: "Spende 214" }),
    );
    expect(router.state.location.search).toBe("?ai_tag=12");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: KI-Schlagwort: Spende" }),
    ).toBeTruthy();
    const page = calls.filter((call) => call.url.pathname === "/api/mails").at(-1)!;
    expect(page.url.searchParams.getAll("ai_tag")).toEqual(["12"]);
    await waitFor(() => expect(facetCalls(calls).at(-1)!.url.search).toBe("?ai_tag=12"));

    // The filtered facets: a theme narrows further, its chip names the theme.
    const themes = await panel("KI-Themen");
    fireEvent.click(await within(themes).findByRole("button", { name: "Spendenaffären 11" }));
    expect(router.state.location.search).toBe("?ai_tag=12&ai_theme=spenden");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: KI-Thema: Spendenaffären" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Filter entfernen: KI-Schlagwort: Spende" }),
    );
    expect(router.state.location.search).toBe("?ai_theme=spenden");
  });

  it("are left out while no mail has a summary", async () => {
    const { calls } = renderApp("/mails", aiApi(aiFacetsEmpty));
    await openInsights();
    await screen.findByRole("heading", { name: "Entitäten", level: 3 });
    await waitFor(() => expect(facetCalls(calls)).toHaveLength(1));
    await screen.findByRole("heading", { name: "Signale", level: 3 });
    expect(screen.queryByRole("heading", { name: "KI-Schlagwörter" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "KI-Themen" })).toBeNull();
  });

  it("fold by their heading", async () => {
    renderApp("/mails", aiApi());
    const tagsPanel = await panel("KI-Schlagwörter");
    const toggle = within(tagsPanel).getByRole("button", { name: "KI-Schlagwörter" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(within(tagsPanel).queryByRole("button", { name: "Spende 214" })).toBeNull();
    expect(within(tagsPanel).getByText("maschinell erzeugt")).toBeTruthy();
    fireEvent.click(toggle);
    expect(within(tagsPanel).getByRole("button", { name: "Spende 214" })).toBeTruthy();
  });
});

describe("adopting an AI tag as a team tag (D310)", () => {
  it("gives every mail carrying it the new team tag, after asking", async () => {
    const { calls } = renderApp("/mails", aiApi());
    fireEvent.click(
      within(await panel("KI-Schlagwörter")).getByRole("button", {
        name: "„Spende“ als Team-Tag übernehmen",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Als Team-Tag übernehmen?" });
    expect(dialog.textContent).toContain(
      "Der Team-Tag „Spende“ geht an 214 Mails mit diesem KI-Schlagwort, ausgeblendete eingeschlossen. Er wird neu angelegt.",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Übernehmen" }));
    expect(
      (await screen.findByText("Team-Tag „Spende“ an 214 Mails vergeben")).getAttribute("role"),
    ).toBe("status");
    expect(adoptCalls(calls).map((call) => [call.url.pathname, call.body])).toEqual([
      ["/api/ai/tags/12/adopt", {}],
    ]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("gives the list's mails carrying it an existing team tag, named in any case", async () => {
    const { calls } = renderApp("/mails?has_attachment=true", (call) =>
      call.url.pathname === "/api/ai/facets" && call.url.searchParams.size
        ? {
            ...aiFacetsFiltered,
            tags: [{ id: 31, label: teamTags[1].name.toUpperCase(), mails: 9 }],
            sampled: true,
          }
        : aiApi()(call),
    );
    const label = teamTags[1].name.toUpperCase();
    fireEvent.click(
      await within(await panel("KI-Schlagwörter")).findByRole("button", {
        name: `„${label}“ als Team-Tag übernehmen`,
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Als Team-Tag übernehmen?" });
    // Counted by the list's summary with the tag added, since the facets took a sample.
    await waitFor(() =>
      expect(dialog.textContent).toContain(
        `Der Team-Tag „${label}“ geht an 38 Mails dieser Liste, die das KI-Schlagwort tragen. Es gibt ihn schon unter den Schlagwörtern.`,
      ),
    );
    const counted = calls.filter(
      (call) => call.url.pathname === "/api/mails/summary" && call.url.searchParams.has("ai_tag"),
    );
    expect(counted.map((call) => call.url.search)).toEqual(["?has_attachment=true&ai_tag=31"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Übernehmen" }));
    expect(await screen.findByText(`Team-Tag „${label}“ an 7 Mails vergeben`)).toBeTruthy();
    const body: AiTagAdopt = { filters: { has_attachment: true } };
    expect(adoptCalls(calls).map((call) => call.body)).toEqual([body]);
  });

  it("says why the backend refused, and keeps the dialog open", async () => {
    const { calls } = renderApp("/mails", (call) =>
      call.url.pathname.endsWith("/adopt")
        ? Response.json({ detail: { code: "too_many_mails", message: "refused" } }, { status: 400 })
        : aiApi()(call),
    );
    fireEvent.click(
      within(await panel("KI-Schlagwörter")).getByRole("button", {
        name: "„Parteitag“ als Team-Tag übernehmen",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Als Team-Tag übernehmen?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Übernehmen" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "Höchstens 50.000 Mails auf einmal; bitte die Liste eingrenzen.",
    );
    expect(adoptCalls(calls)).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
