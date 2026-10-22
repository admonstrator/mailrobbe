import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiQueued, AiSummaryView } from "../../api/types";
import {
  aiSummaryMail,
  aiSummaryNone,
  aiSummaryResult,
  documentDetail,
  mailDetail,
} from "../../test/fixtures";
import { fixtureApi, renderApp, renderElement, type ApiCall } from "../../test/render";
import { SummaryCard } from "./SummaryCard";

const MAIL = mailDetail.id;

const started: AiQueued = {
  queued: 1,
  raised: 0,
  unreadable: 0,
  logos: 0,
  run: "started",
  short: 0,
  estimate: null,
};

/** The fixture backend with the summary endpoints; after a start the summary is `after`. */
function summaryApi(view: AiSummaryView, after: AiSummaryView = view) {
  let current = view;
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/ai/summary") return current;
    if (path === "/api/ai/tasks" && call.method === "POST") {
      current = after;
      return started;
    }
    if (path === "/api/ai/results/501/discard") return { changed: 1 };
    if (path === "/api/ai/tags/12/adopt") return { tag_id: 3, created: false, mails: 1 };
    return fixtureApi(call);
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);

const findCard = () => screen.findByRole("region", { name: "KI-Zusammenfassung" });

/** Lets the summary's answer arrive, for a card that then shows nothing. */
async function settle(calls: ApiCall[]) {
  await waitFor(() =>
    expect(calls.some((call) => call.url.pathname === "/api/ai/summary")).toBe(true),
  );
  await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
}

describe("the card KI-Zusammenfassung", () => {
  it("shows the summary as machine made, with tags, hints and the attachments", async () => {
    renderElement(<SummaryCard target="mail" id={MAIL} />, summaryApi(aiSummaryMail));
    const card = await findCard();
    expect(within(card).getByText("Maschinell erzeugt · local-text:8b · 21.10.2026")).toBeTruthy();
    expect(within(card).getByText(/Herr Brandt schickt die finale Fassung/)).toBeTruthy();
    expect(within(card).getByText("Zusammenfassung der ersten 2 von 5 Abschnitten")).toBeTruthy();
    const tag = within(card).getByRole("link", { name: "Rahmenvereinbarung" });
    expect(tag.getAttribute("href")).toBe("/mails?ai_tag=11");
    expect(tag.getAttribute("title")).toBe("14 Mails mit diesem Schlagwort");
    // a hint's quote opens the mail's text with its words marked
    expect(within(card).getByText("Hinweis: Spendenaffären")).toBeTruthy();
    const quote = within(card).getByRole("link", { name: "„Spenden ohne Quittungen verbuchen“" });
    const href = new URL(quote.getAttribute("href")!, "http://localhost");
    expect(href.pathname).toBe(`/mails/${MAIL}`);
    expect(href.searchParams.get("q")).toBe('"Spenden ohne Quittungen verbuchen"');
    // the summary of the scanned attachment, from its recognised text
    const attachments = within(card).getByRole("region", {
      name: "Zusammenfassungen der Anhänge",
    });
    expect(
      within(attachments)
        .getByRole("link", { name: "Scan_20180306_7499.pdf" })
        .getAttribute("href"),
    ).toBe("/anhaenge/5150");
    expect(
      within(attachments).getByText(
        "Maschinell erzeugt · local-text:8b · 21.10.2026 · aus dem erkannten Text",
      ),
    ).toBeTruthy();
    expect(
      within(attachments).getByText("Eine Quittung über 500 Euro", { exact: false }),
    ).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Neu zusammenfassen" })).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Verwerfen" })).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
  });

  it("says when the text was too short, and when a service in the internet wrote it", async () => {
    const short = {
      ...aiSummaryResult,
      summary: "",
      short: true,
      remote: true,
      parts_read: 1,
      parts_total: 1,
    };
    renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi({ ...aiSummaryNone, result: short }),
    );
    const card = await findCard();
    expect(
      within(card).getByText(
        "Maschinell erzeugt · local-text:8b · 21.10.2026 · über einen Dienst im Internet",
      ),
    ).toBeTruthy();
    expect(
      within(card).getByText(
        "Zu wenig eigener Text für eine Zusammenfassung; nur Schlagwörter und Hinweise.",
      ),
    ).toBeTruthy();
    expect(within(card).queryByText(/Abschnitten/)).toBeNull();
    expect(within(card).getByRole("link", { name: "Spendenquittungen" })).toBeTruthy();
  });

  it("summarises a mail at once and follows its task", async () => {
    const waiting = {
      ...aiSummaryNone,
      task: { id: 9, status: "waiting" as const, parts_done: 0, parts_total: null },
    };
    const { calls } = renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi(aiSummaryNone, waiting),
    );
    const card = await findCard();
    expect(within(card).getByText("Noch keine Zusammenfassung dieser Mail.")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Zusammenfassen" }));
    expect(
      await within(card).findByText(
        "Die Zusammenfassung läuft; sie erscheint hier, sobald sie fertig ist.",
      ),
    ).toBeTruthy();
    expect(posts(calls, "/api/ai/tasks").map((call) => call.body)).toEqual([
      { kind: "summarize", mail_ids: [MAIL], single: true, start: true },
    ]);
    const task = await within(card).findByText(/Für die Zusammenfassung vorgemerkt/);
    expect(within(task).getByRole("link", { name: "zur Seite „KI“" }).getAttribute("href")).toBe(
      "/ki",
    );
    expect(within(card).queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
  });

  it("shows the part a running task is at", async () => {
    const running = {
      ...aiSummaryNone,
      task: { id: 9, status: "running" as const, parts_done: 1, parts_total: 4 },
    };
    renderElement(<SummaryCard target="mail" id={MAIL} />, summaryApi(running));
    const card = await findCard();
    expect(within(card).getByText(/Zusammenfassung läuft · Teil 2 von 4/)).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
    expect(within(card).queryByText("Noch keine Zusammenfassung dieser Mail.")).toBeNull();
  });

  it("says why the last summary failed and offers it again", async () => {
    renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi({ ...aiSummaryNone, failed: "the answer is no JSON object" }),
    );
    const card = await findCard();
    expect(
      within(card).getByText(
        "Die Zusammenfassung ist fehlgeschlagen: the answer is no JSON object",
      ),
    ).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Zusammenfassen" })).toBeTruthy();
  });

  it("summarises again and discards only after a confirmation", async () => {
    const { calls } = renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi(aiSummaryMail),
    );
    const card = await findCard();
    fireEvent.click(within(card).getByRole("button", { name: "Neu zusammenfassen" }));
    const again = await screen.findByRole("dialog", { name: "Neu zusammenfassen?" });
    expect(again.textContent).toContain("ersetzt die bisherige erst, wenn sie da ist");
    fireEvent.click(within(again).getByRole("button", { name: "Jetzt zusammenfassen" }));
    await waitFor(() => expect(posts(calls, "/api/ai/tasks")).toHaveLength(1));
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      kind: "summarize",
      mail_ids: [MAIL],
      single: true,
      start: true,
    });

    fireEvent.click(within(card).getByRole("button", { name: "Verwerfen" }));
    const discard = await screen.findByRole("dialog", { name: "Zusammenfassung verwerfen?" });
    expect(posts(calls, "/api/ai/results/501/discard")).toHaveLength(0);
    fireEvent.click(within(discard).getByRole("button", { name: "Verwerfen" }));
    expect(await within(card).findByText("Die Zusammenfassung ist verworfen.")).toBeTruthy();
    expect(posts(calls, "/api/ai/results/501/discard")).toHaveLength(1);
  });

  it("adopts an AI tag as a team tag of this mail", async () => {
    const { calls } = renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi(aiSummaryMail),
    );
    const card = await findCard();
    const [own] = within(card).getAllByRole("button", {
      name: "„Spendenquittungen“ als Team-Tag übernehmen",
    });
    fireEvent.click(own);
    expect(
      await within(card).findByText("Diese Mail hat jetzt den Team-Tag „Spendenquittungen“."),
    ).toBeTruthy();
    expect(posts(calls, "/api/ai/tags/12/adopt").map((call) => call.body)).toEqual([
      { mail_id: MAIL },
    ]);
  });

  it("offers nothing without a text service, and keeps a summary made earlier", async () => {
    renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi({ ...aiSummaryMail, available: false }),
    );
    const card = await findCard();
    expect(
      within(card).getByText(/Kein Textmodell eingerichtet \(MAILROBBE_AI_TEXT_URL\)/),
    ).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Seite „KI“" }).getAttribute("href")).toBe("/ki");
    expect(within(card).queryByRole("button", { name: "Neu zusammenfassen" })).toBeNull();
    expect(within(card).getByRole("button", { name: "Verwerfen" })).toBeTruthy();
  });

  it("is left out with neither a summary nor a text service", async () => {
    const { calls } = renderElement(
      <SummaryCard target="mail" id={MAIL} />,
      summaryApi({ ...aiSummaryNone, available: false }),
    );
    await settle(calls);
    expect(screen.queryByRole("region", { name: "KI-Zusammenfassung" })).toBeNull();
  });

  it("is left out while the summary cannot be loaded", async () => {
    const { calls } = renderElement(<SummaryCard target="mail" id={MAIL} />);
    await settle(calls);
    expect(screen.queryByRole("region", { name: "KI-Zusammenfassung" })).toBeNull();
  });
});

describe("summaries on the mail and document pages", () => {
  it("stands above the mail's text, and a quote shows its words there", async () => {
    const scrolled: Element[] = [];
    // jsdom does not scroll
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    const { router } = renderApp(`/mails/${MAIL}`, summaryApi(aiSummaryMail));
    const card = await findCard();
    const text = screen.getByRole("region", { name: "Inhalt" });
    expect(card.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(within(card).getByRole("link", { name: "„Rahmenvereinbarung 2026“" }));
    await waitFor(() =>
      expect(new URLSearchParams(router.state.location.search).get("q")).toBe(
        '"Rahmenvereinbarung 2026"',
      ),
    );
    expect(router.state.location.pathname).toBe(`/mails/${MAIL}`);
    expect(scrolled).toEqual([text]);
  });

  it("summarises a document from beside its download", async () => {
    const view = { ...aiSummaryNone };
    const { calls } = renderApp(`/anhaenge/${documentDetail.id}`, summaryApi(view));
    const header = (await screen.findByRole("heading", { level: 1 })).closest("section")!;
    const button = await within(header).findByRole("button", { name: "Zusammenfassen" });
    const download = within(header).getByRole("link", { name: "Herunterladen" });
    expect(download.parentElement).toBe(button.parentElement);
    // the card leaves the offer to the button
    expect(screen.queryByRole("region", { name: "KI-Zusammenfassung" })).toBeNull();
    fireEvent.click(button);
    expect(await within(header).findByText(/Die Zusammenfassung läuft/)).toBeTruthy();
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      kind: "summarize",
      document_ids: [documentDetail.id],
      single: true,
      start: true,
    });
    expect(
      calls
        .find((call) => call.url.pathname === "/api/ai/summary")
        ?.url.searchParams.get("document"),
    ).toBe(String(documentDetail.id));
  });

  it("shows a document's summary with the text it read, without adopting tags", async () => {
    const result = { ...aiSummaryMail.attachments[0].result };
    renderApp(`/anhaenge/${documentDetail.id}`, summaryApi({ ...aiSummaryNone, result }));
    const card = await findCard();
    expect(
      within(card).getByText(
        "Maschinell erzeugt · local-text:8b · 21.10.2026 · aus dem erkannten Text",
      ),
    ).toBeTruthy();
    expect(within(card).getByRole("link", { name: "Spendenquittungen" })).toBeTruthy();
    expect(within(card).queryByRole("button", { name: /als Team-Tag übernehmen/ })).toBeNull();
    const header = screen.getByRole("heading", { level: 1 }).closest("section")!;
    expect(within(header).queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
  });
});
