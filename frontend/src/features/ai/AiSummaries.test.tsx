import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiMailRef, AiResultItem, AiSendItem, AiStatus, AiTaskItem } from "../../api/types";
import {
  aiJobRunning,
  aiResultPage,
  aiSendLogPage,
  aiStatus,
  aiStatusRunning,
  aiStatusText,
  aiTaskPage,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

// The page "KI" with summaries (milestone 17, D300): the text model, its queue, its results.

const mail: AiMailRef = {
  id: 184221,
  subject: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
  date: "2026-10-18T12:32:07Z",
};

const summaryTask: AiTaskItem = {
  ...aiTaskPage.items[0],
  id: 320,
  kind: "summarize",
  document: null,
  status: "running",
  pages_read: 1,
  pages_total: 4,
  target: "mail",
  mail,
};

const summaryResult: AiResultItem = {
  ...aiResultPage.items[0],
  id: 501,
  kind: "summarize",
  document: null,
  engine: "text",
  model: "local-text:8b",
  pages_read: 2,
  pages_text: 0,
  pages_total: 5,
  uncertain: [],
  failed: [],
  characters: 212,
  job_id: 42,
  target: "mail",
  mail,
  tags: 2,
  themes: 1,
};

const sentMail: AiSendItem = {
  ...aiSendLogPage.items[0],
  id: 6,
  kind: "summarize",
  document: null,
  bytes: 9_120,
  target: "mail",
  mail,
};

const withSummaries: AiStatus = {
  ...aiStatusText,
  queue: {
    ...aiStatusText.queue,
    summarize: { waiting: 3, running: 1, done: 5, failed: 0, cancelled: 0 },
  },
  remote_used: true,
};

function api(status: AiStatus) {
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/ai/status") return status;
    if (path === "/api/ai/tasks" && call.method === "GET") {
      return { items: [summaryTask, ...aiTaskPage.items], next_cursor: null };
    }
    if (path === "/api/ai/results") {
      return { items: [summaryResult, ...aiResultPage.items], next_cursor: null };
    }
    if (path === "/api/ai/results/501/discard") return { changed: 1 };
    if (path === "/api/ai/send-log") {
      return { items: [sentMail, ...aiSendLogPage.items], next_cursor: null, total: 2 };
    }
    if (path === "/api/ai/run") return Response.json(aiJobRunning, { status: 202 });
    return fixtureApi(call);
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);

describe("summaries on the AI page", () => {
  it("explains summaries and how to set up a text model", async () => {
    renderApp("/ki", api(aiStatus));
    const services = await screen.findByRole("region", { name: "Dienste" });
    expect(within(services).getByText(/Kein Textmodell eingerichtet/).textContent).toContain(
      "unter Einstellungen mit Adresse und Modell",
    );
    const intro = screen.getByRole("region", { name: "Was die KI macht" });
    expect(intro.textContent).toContain("„maschinell erzeugt“");
    expect(intro.textContent).toContain("sie werden nicht durchsuchbar");
  });

  it("shows the text model and lists summaries by their mail", async () => {
    renderApp("/ki", api(withSummaries));
    const services = await screen.findByRole("region", { name: "Dienste" });
    expect(
      within(services).getByText("Textmodell (zusammenfassen und verschlagworten)"),
    ).toBeTruthy();
    expect(within(services).getByText("http://host.docker.internal:1234/v1")).toBeTruthy();
    expect(within(services).queryByText(/Kein Textmodell eingerichtet/)).toBeNull();

    // the queue counts every kind and names a mail by its subject
    const queue = screen.getByRole("region", { name: "Warteschlange" });
    expect(within(queue).getByRole("button", { name: "vorgemerkt 15" })).toBeTruthy();
    const task = await within(queue).findByRole("link", { name: mail.subject! });
    expect(task.getAttribute("href")).toBe("/mails/184221");
    const taskRow = task.closest("tr")!;
    expect(within(taskRow).getByText("Zusammenfassung")).toBeTruthy();
    expect(within(taskRow).getByText("1 von 4")).toBeTruthy();

    const results = screen.getByRole("region", { name: "Ergebnisse" });
    const result = (await within(results).findByRole("link", { name: mail.subject! })).closest(
      "tr",
    )!;
    expect(within(result).getByText("2 Schlagwörter · 1 Hinweis")).toBeTruthy();
    expect(within(result).getByText("Zusammenfassung")).toBeTruthy();
    expect(within(result).getByText("local-text:8b")).toBeTruthy();
    expect(within(result).getByText("2 von 5")).toBeTruthy();
    expect(within(result).getByText("212")).toBeTruthy();

    const sent = screen.getByRole("region", { name: "Gesendet" });
    expect(
      (await within(sent).findByRole("link", { name: mail.subject! })).getAttribute("href"),
    ).toBe("/mails/184221");
  });

  it("discards a summary after a confirmation", async () => {
    const { calls } = renderApp("/ki", api(withSummaries));
    const results = await screen.findByRole("region", { name: "Ergebnisse" });
    const row = (await within(results).findByRole("link", { name: mail.subject! })).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Verwerfen" }));
    const dialog = await screen.findByRole("dialog", { name: "Zusammenfassung verwerfen?" });
    expect(dialog.textContent).toContain(`„${mail.subject}“`);
    fireEvent.click(within(dialog).getByRole("button", { name: "Verwerfen" }));
    expect(await within(dialog).findByText("Die Zusammenfassung ist verworfen.")).toBeTruthy();
    expect(posts(calls, "/api/ai/results/501/discard")).toHaveLength(1);
  });

  it("starts a run with the text model", async () => {
    const { calls } = renderApp("/ki", api(withSummaries));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect(run.textContent).toContain("3 Zusammenfassungen sind vorgemerkt");
    const model = within(run).getByRole("textbox", { name: "Textmodell" });
    expect(model).toHaveProperty("value", "local-text:8b");
    fireEvent.change(model, { target: { value: " local-text:14b " } });
    fireEvent.click(within(run).getByRole("button", { name: "KI-Lauf starten" }));
    await waitFor(() => expect(posts(calls, "/api/ai/run")).toHaveLength(1));
    expect(posts(calls, "/api/ai/run")[0].body).toEqual({
      engine: "auto",
      max_pages: 50,
      vision_model: "qwen2.5vl:7b",
      text_model: "local-text:14b",
      max_minutes: 180,
    });
  });

  it("starts a run for summaries alone", async () => {
    const status = {
      ...withSummaries,
      queue: { ...withSummaries.queue, ocr: { ...withSummaries.queue.ocr, waiting: 0 } },
    };
    renderApp("/ki", api(status));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect(run.textContent).not.toContain("Nichts vorgemerkt");
    expect(within(run).getByRole("button", { name: "KI-Lauf starten" })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("shows the summaries of a live run", async () => {
    const job = { ...aiJobRunning, progress: { ...aiJobRunning.progress, summaries: 4 } };
    renderApp("/ki", api({ ...aiStatusRunning, job }));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect((await within(run).findByText(/Dokumente gelesen/)).textContent).toContain(
      "4 Zusammenfassungen",
    );
  });
});
