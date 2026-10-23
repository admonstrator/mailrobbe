import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { signalFacetsFiltered, signalOverviewNever, summaryFiltered } from "../../test/fixtures";
import { openInsights, rows } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const facetCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/mails/signals");

/** The signal facets in the panel "Einblicke", which this opens. */
async function facets(): Promise<HTMLElement> {
  const insights = await openInsights();
  const heading = await within(insights).findByRole("heading", { name: "Signale", level: 3 });
  return heading.closest("section")!;
}

/** The labels of the chips' toggles, once the word fields carry their themes' names. */
async function chipTexts(panel: HTMLElement): Promise<string[]> {
  const group = await within(panel).findByRole("group", { name: "Signale" });
  await within(group).findByRole("button", { name: /^Wortfeld Spendenaffären/ });
  return within(group)
    .getAllByRole("button")
    .map((chip) => chip.textContent ?? "");
}

describe("signal facets in the panel Einblicke", () => {
  it("show how many mails carry each signal, in the response's order", async () => {
    const { calls } = renderApp("/mails");
    const panel = await facets();
    await within(panel).findByText("in allen Mails");
    expect(await chipTexts(panel)).toEqual([
      "Private Adresse 18.240",
      "Von intern an privat 6.120",
      "Von privat an intern 4.877",
      "Private Zweitadresse 1.934",
      "Blindkopie (Bcc) 9.821",
      "Viele Empfänger 3.315",
      "Weiterleitung 22.408",
      "Weiterleitung nach außen 3.127",
      "Nachts 15.873",
      "Wochenende 21.190",
      "Wortfeld Spendenaffären 2.210",
      "Wortfeld Gewalt 412",
    ]);
    expect(within(panel).getByRole("link", { name: "Regel von Nachts" }).getAttribute("href")).toBe(
      "/auffaelligkeiten#signal-night",
    );
    expect(within(panel).getByRole("link", { name: "Was Signale sind" }).getAttribute("href")).toBe(
      "/auffaelligkeiten",
    );
    // Its own request with the list's filters (none), so the list never waits for it.
    expect(facetCalls(calls).map((call) => call.url.search)).toEqual([""]);
  });

  it("narrow the list with a click, keep the other filters, and widen it with a second", async () => {
    const { router, calls } = renderApp("/mails?has_attachment=true");
    const panel = await facets();
    const weekend = await within(panel).findByRole("button", { name: "Wochenende 140" });
    expect(within(panel).getByText("in 1.207 Treffern")).toBeTruthy();
    expect(weekend.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(weekend);
    expect(router.state.location.search).toBe("?has_attachment=true&signal=weekend");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Signal: Wochenende" }),
    ).toBeTruthy();
    await waitFor(() =>
      expect(facetCalls(calls).at(-1)!.url.search).toBe("?has_attachment=true&signal=weekend"),
    );
    const page = calls.filter((call) => call.url.pathname === "/api/mails").at(-1)!;
    expect(page.url.searchParams.getAll("signal")).toEqual(["weekend"]);

    // A word field narrows further, and its chip names the theme.
    fireEvent.click(
      await within(panel).findByRole("button", { name: "Wortfeld Spendenaffären 77" }),
    );
    expect(new URLSearchParams(router.state.location.search).getAll("signal")).toEqual([
      "weekend",
      "term:spenden",
    ]);
    await screen.findByRole("button", {
      name: "Filter entfernen: Signal: Wortfeld Spendenaffären",
    });

    const selected = within(panel).getByRole("button", { name: "Wochenende 140" });
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(selected);
    expect(router.state.location.search).toBe("?has_attachment=true&signal=term%3Aspenden");
  });

  it("start the list again at its first page", async () => {
    const { router } = renderApp("/mails?q=Vertrag&cursor=abc&page=3");
    const panel = await facets();
    fireEvent.click(await within(panel).findByRole("button", { name: "Blindkopie (Bcc) 12" }));
    expect(router.state.location.search).toBe("?q=Vertrag&signal=bcc");
  });

  it("say when they count a sample of the matches", async () => {
    renderApp("/mails?q=Vertrag", (call) => {
      if (call.url.pathname === "/api/mails/signals") {
        return { ...signalFacetsFiltered, mails: 10000, sampled: true };
      }
      if (call.url.pathname === "/api/mails/summary") {
        return { ...summaryFiltered, total: 23456, exact: true };
      }
      return fixtureApi(call);
    });
    const panel = await facets();
    expect(
      await within(panel).findByText("in 10.000 von 23.456 Treffern (Stichprobe)"),
    ).toBeTruthy();
  });

  it("say that the next import computes them while no signals phase ran", async () => {
    renderApp("/mails", (call) => {
      if (call.url.pathname === "/api/mails/signals") {
        return { signals: {}, mails: null, sampled: false };
      }
      if (call.url.pathname === "/api/signals") return signalOverviewNever;
      return fixtureApi(call);
    });
    const panel = await facets();
    expect(await within(panel).findByText("Keine Signale")).toBeTruthy();
    expect(
      await within(panel).findByText("Signale werden beim nächsten Import berechnet."),
    ).toBeTruthy();
  });

  it("say none holds for the filter's mails", async () => {
    renderApp("/mails?has_attachment=true", (call) =>
      call.url.pathname === "/api/mails/signals"
        ? { signals: {}, mails: 1207, sampled: false }
        : fixtureApi(call),
    );
    const panel = await facets();
    expect(await within(panel).findByText("Keine Signale in diesen Mails")).toBeTruthy();
    expect(within(panel).queryByText("Signale werden beim nächsten Import berechnet.")).toBeNull();
  });

  it("step aside when the filter has no hits", async () => {
    const { calls } = renderApp("/mails?q=nichts", (call) =>
      call.url.pathname === "/api/mails/signals"
        ? { signals: {}, mails: 0, sampled: false }
        : fixtureApi(call),
    );
    await openInsights();
    await waitFor(() => expect(facetCalls(calls)).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Signale", level: 3 })).toBeNull(),
    );
  });

  it("offer a retry when they fail, while the list stays", async () => {
    renderApp("/mails", (call) =>
      call.url.pathname === "/api/mails/signals"
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    const panel = await facets();
    expect(
      await within(panel).findByText("Die Signale konnten nicht geladen werden."),
    ).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Erneut versuchen" })).toBeTruthy();
    expect(
      screen.getByRole("link", {
        name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      }),
    ).toBeTruthy();
  });

  it("ask for nothing while the panel is closed", async () => {
    const { calls } = renderApp("/mails?has_attachment=true");
    await rows();
    expect(facetCalls(calls)).toHaveLength(0);
    await chipTexts(await facets());
    expect(facetCalls(calls)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("heading", { name: "Signale", level: 3 })).toBeNull();
  });
});
