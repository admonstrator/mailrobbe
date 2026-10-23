import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MailDkim, MailHits } from "../../api/types";
import { mailDetail, wholeWordHits } from "../../test/fixtures";
import { fixtureApi, renderApp } from "../../test/render";
import { stubIntersectionObserver } from "../../test/scroll";

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
    // The technical fields and the DKIM check are folded below the text until opened once.
    const tech = card("Technische Angaben");
    expect(within(tech).queryByText(/export-2026-Q4\.mbox/)).toBeNull();
    fireEvent.click(within(tech).getByRole("button", { name: "Technische Angaben" }));
    expect(
      within(tech).getByText("export-2026-Q4.mbox · Offset 1.883.204.117 · 184 KB", {
        exact: false,
      }),
    ).toBeTruthy();

    const dkim = card("DKIM-Prüfung");
    fireEvent.click(within(dkim).getByRole("button", { name: "DKIM-Prüfung" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Zitat einblenden (5 Zeilen)" }));
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

  it("keeps subject, status and the steps in a bar once the header is scrolled away", async () => {
    const observer = stubIntersectionObserver();
    const { router } = renderApp(`/mails/184221?${listQuery}`);
    await screen.findByText("Treffer 1 von 1.207");
    const bar = () => screen.queryByRole("region", { name: "Kopfzeile der Mail" });
    expect(bar()).toBeNull();
    // Below the window, as on a short window before scrolling: no bar either.
    observer.place("below");
    expect(bar()).toBeNull();

    observer.place("above");
    const compact = bar()!;
    const subject = "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung";
    expect(within(compact).getByTitle(subject).textContent).toBe(subject);
    expect(within(compact).getByTitle("anna.keller@nordlicht-gmbh.example").textContent).toBe(
      "Anna Keller",
    );
    expect(within(compact).getByText("18.10.2026 14:32")).toBeTruthy();
    expect(within(compact).getByText("DKIM gültig")).toBeTruthy();
    expect(within(compact).getByRole("link", { name: "Nächste ›" }).getAttribute("href")).toBe(
      `/mails/184190?${listQuery}`,
    );
    expect(within(compact).getByText("‹ Vorherige").getAttribute("aria-disabled")).toBe("true");

    // The keys work as before, and back at the top the bar goes.
    observer.place("visible");
    expect(bar()).toBeNull();
    observer.place("above");
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/mails/184190"));
  });

  it("shows a preview over the page, whose keys stay in it", async () => {
    const { router, calls } = renderApp(`/mails/184221?${listQuery}`);
    await screen.findByText("Treffer 1 von 1.207");
    const attachments = screen.getByRole("heading", { name: "Anhänge (2)" }).closest("section")!;
    expect(screen.getByRole("main").contains(attachments)).toBe(true);

    fireEvent.click(
      within(attachments).getByRole("button", { name: "Rahmenvereinbarung_2026_final.pdf" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Rahmenvereinbarung_2026_final.pdf" });
    expect(
      await within(dialog).findByTitle("PDF-Vorschau von Rahmenvereinbarung_2026_final.pdf"),
    ).toBeTruthy();
    // Neither the next mail nor a review status: the keys belong to the preview, whose arrows
    // go to the next attachment (D331).
    fireEvent.keyDown(dialog, { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "g" });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(router.state.location.pathname).toBe("/mails/184221");
    expect(calls.filter((call) => call.method !== "GET")).toEqual([]);
    const next = screen.getByRole("dialog", { name: "Aenderungsprotokoll.xlsx" });
    expect(within(next).getByText("Anhang 2 von 2")).toBeTruthy();

    fireEvent.click(within(next).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/mails/184190"));
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
      "Suchtreffer für „Haftung“: im Text · in den Anhängen Rahmenvereinbarung_2026_final.pdf," +
        " Aenderungsprotokoll.xlsx",
    );
    expect(calls.find((call) => call.url.pathname.endsWith("/hits"))!.url.search).toBe(
      "?q=Haftung",
    );
    // The stem marks the longer word in the text; the quoted part has one more place and opens.
    expect(await screen.findByText("2 Fundstellen markiert")).toBeTruthy();
    expect(screen.getByText("Haftungsklausel").tagName).toBe("MARK");
    expect(
      screen.getByRole("button", { name: "Zitat ausblenden (5 Zeilen, 1 Fundstelle)" }),
    ).toBeTruthy();
    const quoted = screen.getByText(/danke für den Entwurf/);
    expect(within(quoted).getByText("Haftung").tagName).toBe("MARK");

    // The entities card names the attachment too.
    const card = within(screen.getByRole("heading", { name: /^Anhänge/ }).closest("section")!);
    const pdf = card
      .getByText("Rahmenvereinbarung_2026_final.pdf", { selector: "span *, span" })
      .closest("li")!;
    expect([...pdf.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "Haftung",
      "Haftung",
    ]);
    const sheet = card
      .getByText("Aenderungsprotokoll.xlsx", { selector: "span *, span" })
      .closest("li")!;
    expect(within(sheet).getByText("Suchwort im Text, in einer anderen Wortform")).toBeTruthy();
    fireEvent.click(within(hits).getByRole("button", { name: "Aenderungsprotokoll.xlsx" }));
    expect(scrolled).toEqual([sheet]);
  });

  it("asks for the hits in the list's places and as whole words, and marks only those", async () => {
    const list = "q=Haftung&scope=body&scope=attachment&whole_word=true&min_hits=2";
    const { calls } = renderApp(`/mails/184221?${list}`, (call) =>
      call.url.pathname.endsWith("/hits") ? wholeWordHits : fixtureApi(call),
    );

    const hits = await screen.findByRole("region", { name: "Suchtreffer" });
    expect(hits.textContent).toBe(
      "Suchtreffer für „Haftung“ als ganzes Wort: im Text (1) · im Anhang" +
        " Rahmenvereinbarung_2026_final.pdf (2)",
    );
    // q, places and whole words; the minimum only narrows the list.
    expect(calls.find((call) => call.url.pathname.endsWith("/hits"))!.url.search).toBe(
      "?q=Haftung&scope=body&scope=attachment&whole_word=true",
    );
    // Not the "Haftungsklausel" of the text: only the quoted "Haftung", which opens by itself.
    expect(await screen.findByText("1 Fundstelle markiert")).toBeTruthy();
    expect(screen.getByText(/Haftungsklausel/).tagName).not.toBe("MARK");
    const quoted = screen.getByText(/danke für den Entwurf/);
    expect([...quoted.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "Haftung",
    ]);
    const card = within(screen.getByRole("heading", { name: /^Anhänge/ }).closest("section")!);
    const pdf = card
      .getByText("Rahmenvereinbarung_2026_final.pdf", { selector: "span *, span" })
      .closest("li")!;
    expect([...pdf.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
      "Haftung",
      "Haftung",
    ]);
  });

  it("names the subject and a file name holding a word, each with its count (D176)", async () => {
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    const named: MailHits = {
      ...wholeWordHits,
      in_subject: true,
      attachments: [
        ...wholeWordHits.attachments,
        { attachment_id: 902, in_name: true, snippet: null, in_text: false },
      ],
      counts: { subject: 1, body: 3, attachment: 2, filename: 1 },
    };
    renderApp(`/mails/184221?${new URLSearchParams({ q: "Haftung" })}`, (call) =>
      call.url.pathname.endsWith("/hits") ? named : fixtureApi(call),
    );
    const hits = await screen.findByRole("region", { name: "Suchtreffer" });
    expect(hits.textContent).toBe(
      "Suchtreffer für „Haftung“ als ganzes Wort: im Betreff (1) · im Text (3) · im Anhang" +
        " Rahmenvereinbarung_2026_final.pdf (2) · im Dateinamen Aenderungsprotokoll.xlsx (1)",
    );
    const card = within(screen.getByRole("heading", { name: /^Anhänge/ }).closest("section")!);
    const sheet = card
      .getByText("Aenderungsprotokoll.xlsx", { selector: "span *, span" })
      .closest("li")!;
    expect(within(sheet).getByText("Suchwort im Dateinamen")).toBeTruthy();
    fireEvent.click(within(hits).getByRole("button", { name: "Aenderungsprotokoll.xlsx" }));
    expect(scrolled).toEqual([sheet]);
    // The subject is in view above the card, so it is no jump.
    expect(within(hits).queryByRole("button", { name: /Betreff/ })).toBeNull();
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
    // Neu prüfen works folded too, and opens the box to show the result.
    fireEvent.click(await screen.findByRole("button", { name: "Neu prüfen" }));
    expect(await screen.findByText("Body nach dem Signieren verändert")).toBeTruthy();
    expect(screen.getByText("DKIM ungültig")).toBeTruthy();
    expect(screen.getByText("abweichend")).toBeTruthy();
    expect(calls.some((call) => call.method === "POST")).toBe(true);
  });

  it("names labelled participants by the team's label, with the role (D157)", async () => {
    const label = { name: "Kassenwartin Nord", role: "Schatzmeisterin" };
    const participants = mailDetail.participants.map((person) =>
      person.person_id === 11 ? { ...person, label } : person,
    );
    renderApp("/mails/184221", (call) =>
      call.url.pathname === "/api/mails/184221"
        ? { ...mailDetail, participants }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Beteiligte" });
    const people = card("Beteiligte");
    const anna = within(people).getByRole("link", { name: /Kassenwartin Nord/ });
    expect(anna.textContent).toBe("KNKassenwartin Nord · Schatzmeisterin · Absender");
    expect(anna.getAttribute("title")).toBe("anna.keller@nordlicht-gmbh.example");
    // The header keeps the address beside the name.
    expect(screen.getAllByRole("link", { name: "Kassenwartin Nord" }).length).toBeGreaterThan(0);
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
