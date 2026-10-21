import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MailDkim } from "../../api/types";
import { mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp } from "../../test/render";

const listQuery = new URLSearchParams({ q: "subject:Vertrag" }).toString();

function card(heading: string): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("section")!;
}

describe("mail detail", () => {
  it("renders header, DKIM check, participants, thread and text", async () => {
    const { calls } = renderApp(`/mails/184221?${listQuery}`);

    expect(
      await screen.findByRole("heading", {
        name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      }),
    ).toBeTruthy();
    expect(screen.getByText("DKIM gültig")).toBeTruthy();
    expect(screen.getByText("So, 18.10.2026 14:32:07")).toBeTruthy();
    expect(
      screen.getByText("export-2026-Q4.mbox · Offset 1.883.204.117 · 184 KB", { exact: false }),
    ).toBeTruthy();

    const dkim = card("DKIM-Prüfung");
    expect(
      within(dkim).getByText("geprüft am 20.10.2026 03:14 · DNS-Antwort aus Cache (TTL 12 h)"),
    ).toBeTruthy();
    expect(within(dkim).getByText("nordlicht-gmbh.example")).toBeTruthy();
    expect(within(dkim).getByText("mail2025")).toBeTruthy();
    expect(within(dkim).getByText("rsa-sha256 · 2048 Bit")).toBeTruthy();
    expect(
      within(dkim).getByText("from:to:cc:subject:date:message-id:mime-version:content-type"),
    ).toBeTruthy();
    expect(within(dkim).getByText("übereinstimmend")).toBeTruthy();
    expect(within(dkim).getByText("ja (aligned)")).toBeTruthy();

    const people = card("Beteiligte");
    const links = within(people).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/personen/11",
      "/personen/12",
      "/personen/15",
      "/personen/13",
      "/karte?center=11,12,15,13",
    ]);
    expect(within(people).getByText("· Absender")).toBeTruthy();
    expect(within(people).getByText("· Cc")).toBeTruthy();
    expect(within(people).getByText("Diese 4 im Graphen zeigen")).toBeTruthy();

    const thread = card("Thread (4 Mails)");
    expect(within(within(thread).getByRole("list")).getAllByRole("link")).toHaveLength(3);
    expect(within(thread).getByText(/\(diese Mail\)/)).toBeTruthy();
    // The whole thread as a list and on the timeline, by its thread id (D95).
    expect(
      within(thread)
        .getByRole("link", { name: "Alle Mails des Threads als Liste" })
        .getAttribute("href"),
    ).toBe("/mails?thread=184001");
    expect(
      within(thread).getByRole("link", { name: "Thread in der Zeitachse" }).getAttribute("href"),
    ).toBe("/zeitachse?thread=184001");

    expect(await screen.findByText(/Hallo Herr Brandt, hallo Herr Hofmann/)).toBeTruthy();
    expect(screen.queryByText(/danke für den Entwurf/)).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Zitierten Verlauf einblenden (7 Zeilen)" }),
    );
    expect(screen.getByText(/danke für den Entwurf/)).toBeTruthy();

    await waitFor(() => expect(screen.getByText("Treffer 1 von 1.207")).toBeTruthy());
    const path = screen.getByRole("navigation", { name: "Pfad" });
    expect(within(path).getByRole("link", { name: "Mails" }).getAttribute("href")).toBe(
      `/mails?${listQuery}`,
    );
    expect(screen.getByRole("link", { name: "Nächste ›" }).getAttribute("href")).toBe(
      `/mails/184190?${listQuery}`,
    );
    const neighbors = calls.find((call) => call.url.pathname.endsWith("/neighbors"))!;
    expect(neighbors.url.searchParams.get("q")).toBe("subject:Vertrag");
    // The other views are read from the MBOX only when opened.
    expect(calls.filter((call) => call.url.pathname.endsWith("/body"))).toHaveLength(1);
  });

  it("goes to the next mail with the arrow key", async () => {
    const { router } = renderApp(`/mails/184221?${listQuery}`);
    await screen.findByText("Treffer 1 von 1.207");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/mails/184190"));
    expect(router.state.location.search).toBe(`?${listQuery}`);
  });

  it("walks a person's mail list from the profile, role included", async () => {
    const personList = "hide_duplicates=true&person=11&person_role=sent";
    const { calls } = renderApp(`/mails/184221?${personList}`);
    await screen.findByText("Treffer 1 von 412.318");
    const neighbors = calls.find((call) => call.url.pathname.endsWith("/neighbors"))!;
    expect(neighbors.url.search).toBe(`?${personList}`);
    expect(screen.getByRole("link", { name: "Nächste ›" }).getAttribute("href")).toBe(
      `/mails/184190?${personList}`,
    );
  });

  it("marks where the list's search words occur: subject, text, quoted text, attachments", async () => {
    const scrolled: Element[] = [];
    // jsdom does not scroll
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    const { calls } = renderApp(`/mails/184221?${new URLSearchParams({ q: "Haftung" })}`);

    const hits = await screen.findByRole("region", { name: "Suchtreffer" });
    expect(hits.textContent).toBe(
      "Suchtreffer für „Haftung“: im Text der Mail · im Anhang Rahmenvereinbarung_2026_final.pdf" +
        " · im Anhang Aenderungsprotokoll.xlsx",
    );
    expect(calls.find((call) => call.url.pathname.endsWith("/hits"))!.url.search).toBe(
      "?q=Haftung",
    );
    // The stem marks the longer word in the text; the quoted part has one more place.
    expect(await screen.findByText("2 Fundstellen markiert")).toBeTruthy();
    expect(screen.getByText("Haftungsklausel").tagName).toBe("MARK");
    fireEvent.click(
      screen.getByRole("button", { name: "Zitierten Verlauf einblenden (7 Zeilen, 1 Fundstelle)" }),
    );
    const quoted = screen.getByText(/danke für den Entwurf/);
    expect(within(quoted).getByText("Haftung").tagName).toBe("MARK");

    const pdf = screen
      .getByText("Rahmenvereinbarung_2026_final.pdf", { selector: "span *, span" })
      .closest("li")!;
    expect([...pdf.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "Haftung",
      "Haftung",
    ]);
    const sheet = screen
      .getByText("Aenderungsprotokoll.xlsx", { selector: "span *, span" })
      .closest("li")!;
    expect(within(sheet).getByText("Suchwort im Text, in einer anderen Wortform")).toBeTruthy();
    fireEvent.click(
      within(hits).getByRole("button", { name: "im Anhang Aenderungsprotokoll.xlsx" }),
    );
    expect(scrolled).toEqual([sheet]);
  });

  it("marks nothing without full text words in the list's query", async () => {
    renderApp(`/mails/184221?${listQuery}`);
    expect(await screen.findByText(/Hallo Herr Brandt/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Suchtreffer" })).toBeNull();
    expect(document.querySelector("mark")).toBeNull();
  });

  it("shows the result of Neu prüfen", async () => {
    const failed: MailDkim = {
      status: "fail",
      signatures: [
        {
          ...mailDetail.dkim.signatures[0],
          status: "fail",
          reason: "body_hash_mismatch",
          body_hash_ok: false,
        },
      ],
    };
    const { calls } = renderApp("/mails/184221", (call) =>
      call.url.pathname.endsWith("/dkim/recheck") ? failed : fixtureApi(call),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Neu prüfen" }));
    expect(await screen.findByText("Body nach dem Signieren verändert")).toBeTruthy();
    expect(screen.getByText("DKIM ungültig")).toBeTruthy();
    expect(screen.getByText("abweichend")).toBeTruthy();
    expect(calls.some((call) => call.method === "POST")).toBe(true);
  });

  it("says when a mail does not exist", async () => {
    renderApp("/mails/999", (call) =>
      call.url.pathname === "/api/mails/999"
        ? Response.json({ detail: { code: "not_found", message: "no mail" } }, { status: 404 })
        : fixtureApi(call),
    );
    expect(await screen.findByText("Diese Mail gibt es nicht.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zur Mailliste" }).getAttribute("href")).toBe("/mails");
  });

  it("names a missing MBOX file instead of showing the text", async () => {
    renderApp("/mails/184221", (call) =>
      call.url.pathname.endsWith("/body")
        ? Response.json(
            { detail: { code: "source_missing", message: "file missing" } },
            { status: 409 },
          )
        : fixtureApi(call),
    );
    expect(await screen.findByText("Die MBOX-Datei ist nicht erreichbar.")).toBeTruthy();
  });
});
