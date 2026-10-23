import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiQueued, AiQueueRequest, AiStatus, ErrorCode } from "../../api/types";
import { aiStatus, aiStatusText, summarizePreview, summaryFiltered } from "../../test/fixtures";
import { fixtureApi, renderApp, renderElement, type ApiCall } from "../../test/render";
import {
  durationText,
  NO_TEXT_SERVICE,
  SummarizeManyDialog,
  summarizedText,
  type SummarizeSelection,
} from "./SummarizeManyDialog";

const apiError = (code: ErrorCode, status = 400) =>
  Response.json({ detail: { code, message: "refused" } }, { status });

/** The fixture backend with the AI status and POST /api/ai/tasks: the preview, and what start
 *  answered; either may be an error instead. */
function summarizeApi({
  status = aiStatusText,
  preview = summarizePreview,
  started = { ...summarizePreview, run: "started" },
}: {
  status?: AiStatus;
  preview?: AiQueued | Response;
  started?: AiQueued | Response;
} = {}) {
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/ai/status") return status;
    if (path === "/api/ai/tasks" && call.method === "POST") {
      return (call.body as AiQueueRequest).preview ? preview : started;
    }
    if (path === "/api/mails/summary" && call.url.search) return summaryFiltered;
    return fixtureApi(call);
  };
}

const taskCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === "/api/ai/tasks");

function renderDialog(
  selection: SummarizeSelection,
  api: (call: ApiCall) => unknown = summarizeApi(),
) {
  return renderElement(<SummarizeManyDialog selection={selection} onClose={() => {}} />, api);
}

const dialog = () => screen.getByRole("dialog", { name: "Zusammenfassen" });

describe("summarising many (D308)", () => {
  it("previews how many, how many are short and how long, then queues and starts", async () => {
    const { calls } = renderDialog({ mail_filters: { has_attachment: true } });
    expect(await within(dialog()).findByText("1.207 Mails")).toBeTruthy();
    const facts = within(dialog())
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(facts).toEqual([
      "davon 312 mit zu wenig eigenem Text: nur Schlagwörter und Hinweise",
      "Dauer etwa 2 Std. 10 Min. (geschätzt) mit text-local",
    ]);
    expect(taskCalls(calls).map((call) => call.body)).toEqual([
      { kind: "summarize", mail_filters: { has_attachment: true }, preview: true },
    ]);

    fireEvent.click(within(dialog()).getByRole("button", { name: "Zusammenfassen" }));
    expect((await within(dialog()).findByRole("status")).textContent).toBe(
      "1.207 vorgemerkt; der Lauf hat begonnen.",
    );
    expect(taskCalls(calls).at(-1)!.body).toEqual({
      kind: "summarize",
      mail_filters: { has_attachment: true },
      start: true,
    });
    expect(
      within(dialog()).getByRole("link", { name: "zur Seite „KI“" }).getAttribute("href"),
    ).toBe("/ki");
    expect(within(dialog()).getByRole("button", { name: "Schließen" })).toBeTruthy();
  });

  it("names documents and what cannot be summarised, measured times without „geschätzt“", async () => {
    const preview: AiQueued = {
      ...summarizePreview,
      queued: 40,
      raised: 2,
      unreadable: 3,
      short: 0,
      estimate: {
        model: "text-local",
        tasks: 42,
        tokens: 90_000,
        seconds: 1_500,
        estimated: false,
      },
    };
    const { calls } = renderDialog({ filters: { kind: ["pdf"] } }, summarizeApi({ preview }));
    expect(await within(dialog()).findByText("42 Dokumente")).toBeTruthy();
    expect(
      within(dialog())
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "davon 2 schon vorgemerkt",
      "3 Dokumente ohne Text, der sich zusammenfassen ließe, bleiben außen vor",
      "Dauer etwa 25 Min. mit text-local",
    ]);
    expect(taskCalls(calls)[0].body).toEqual({
      kind: "summarize",
      filters: { kind: ["pdf"] },
      preview: true,
    });
  });

  it("offers nothing to start when nothing can be summarised", async () => {
    const preview: AiQueued = { ...summarizePreview, queued: 0, unreadable: 2, short: 0 };
    renderDialog({ mail_ids: [4711, 4712] }, summarizeApi({ preview }));
    expect(
      await within(dialog()).findByText(
        "Nichts zusammenzufassen: Diese Mails haben keinen Text, der sich zusammenfassen ließe.",
      ),
    ).toBeTruthy();
    expect(
      (within(dialog()).getByRole("button", { name: "Zusammenfassen" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("says the limit of one request", async () => {
    renderDialog({ mail_filters: {} }, summarizeApi({ preview: apiError("too_many_mails") }));
    expect((await within(dialog()).findByRole("alert")).textContent).toBe(
      "Höchstens 50.000 auf einmal; bitte die Auswahl eingrenzen.",
    );
  });

  it("says when no text model is set up, with a link to the AI page", async () => {
    renderDialog({ mail_ids: [4711] }, summarizeApi({ preview: apiError("invalid_option") }));
    expect((await within(dialog()).findByRole("alert")).textContent).toBe(
      "Kein Textmodell eingerichtet (System › Einstellungen).",
    );
    expect(
      within(dialog()).getByRole("link", { name: "zur Seite „KI“" }).getAttribute("href"),
    ).toBe("/ki");
    expect(within(dialog()).queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
  });

  it("says what start did: a run began, one runs already, or it waits for the import", () => {
    expect(summarizedText({ ...summarizePreview, run: "started" })).toBe(
      "1.207 vorgemerkt; der Lauf hat begonnen.",
    );
    expect(summarizedText({ ...summarizePreview, queued: 10, raised: 2, run: "running" })).toBe(
      "12 vorgemerkt; ein KI-Lauf läuft schon und nimmt sie mit.",
    );
    expect(summarizedText({ ...summarizePreview, run: "busy" })).toBe(
      "1.207 vorgemerkt; der Lauf wartet, bis der Import fertig ist.",
    );
    expect(summarizedText({ ...summarizePreview, queued: 0, raised: 0 })).toBe(
      "Nichts vorgemerkt: Diese Auswahl hat nichts zusammenzufassen.",
    );
  });

  it("shows a busy start in the dialog", async () => {
    renderDialog(
      { mail_ids: [4711] },
      summarizeApi({
        preview: { ...summarizePreview, queued: 1, short: 0 },
        started: { ...summarizePreview, queued: 1, run: "busy" },
      }),
    );
    await within(dialog()).findByText("1 Mail");
    fireEvent.click(within(dialog()).getByRole("button", { name: "Zusammenfassen" }));
    await waitFor(() =>
      expect(within(dialog()).getByRole("status").textContent).toBe(
        "1 vorgemerkt; der Lauf wartet, bis der Import fertig ist.",
      ),
    );
  });

  it("writes durations in hours and minutes", () => {
    expect(durationText(20)).toBe("weniger als 1 Min.");
    expect(durationText(1_500)).toBe("etwa 25 Min.");
    expect(durationText(7_800)).toBe("etwa 2 Std. 10 Min.");
    expect(durationText(7_200)).toBe("etwa 2 Std.");
    expect(durationText(26 * 3_600)).toBe("etwa 1 Tag 2 Std.");
    expect(durationText(72 * 3_600)).toBe("etwa 3 Tage");
  });
});

describe("„Zusammenfassen“ where many are chosen", () => {
  it("on the AI page, everything without a summary", async () => {
    const { calls } = renderApp("/ki", summarizeApi());
    const card = await screen.findByRole("region", { name: "Alles zusammenfassen" });
    const button = within(card).getByRole("button", { name: "Alles zusammenfassen" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    expect(await within(dialog()).findByText("1.207 Mails und Dokumente")).toBeTruthy();
    expect(taskCalls(calls)[0].body).toEqual({
      kind: "summarize",
      everything: true,
      preview: true,
    });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Zusammenfassen" }));
    await within(dialog()).findByRole("status");
    expect(taskCalls(calls).at(-1)!.body).toEqual({
      kind: "summarize",
      everything: true,
      start: true,
    });
  });

  it("in the mail list's bulk bar: the selected mails, or every match by the filters", async () => {
    const { calls } = renderApp("/mails?has_attachment=true", summarizeApi());
    const box = await screen.findAllByRole("checkbox", { name: /^Auswählen: / });
    fireEvent.click(box[0]);
    fireEvent.click(box[1]);
    const bar = screen.getByRole("region", { name: "Auswahl" });
    const button = within(bar).getByRole("button", { name: "Zusammenfassen" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await within(dialog()).findByText("1.207 Mails");
    const ids = (taskCalls(calls)[0].body as AiQueueRequest).mail_ids;
    expect(ids).toHaveLength(2);
    fireEvent.click(within(dialog()).getByRole("button", { name: "Abbrechen" }));

    // Above 1,000 the bulk bar asks first.
    fireEvent.click(within(bar).getByRole("button", { name: "Alle 1.207 Treffer auswählen" }));
    fireEvent.click(within(bar).getByRole("button", { name: "Alle auswählen" }));
    await within(bar).findByText("Alle 1.207 Treffer ausgewählt");
    fireEvent.click(within(bar).getByRole("button", { name: "Zusammenfassen" }));
    await within(dialog()).findByText("1.207 Mails");
    expect(taskCalls(calls).at(-1)!.body).toEqual({
      kind: "summarize",
      mail_filters: { has_attachment: true },
      preview: true,
    });
  });

  it("in the document list when it is filtered, for its filters", async () => {
    const { calls } = renderApp("/anhaenge?kind=pdf", summarizeApi());
    const button = await screen.findByRole("button", { name: "Zusammenfassen" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await within(dialog()).findByText("1.207 Dokumente");
    expect(taskCalls(calls)[0].body).toEqual({
      kind: "summarize",
      filters: { kind: ["pdf"] },
      preview: true,
    });
  });

  it("not in the unfiltered document list", async () => {
    renderApp("/anhaenge", summarizeApi());
    await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
    expect(screen.queryByRole("button", { name: "Zusammenfassen" })).toBeNull();
  });

  it("on an Akte, for its mails", async () => {
    const { calls } = renderApp("/akten/1", summarizeApi());
    const button = await screen.findByRole("button", { name: "Zusammenfassen" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(button);
    await within(dialog()).findByText("1.207 Mails");
    expect(taskCalls(calls)[0].body).toEqual({
      kind: "summarize",
      mail_filters: { collection: [1] },
      preview: true,
    });
  });

  it("disabled with the missing setting while no text service is usable (D300)", async () => {
    const { calls } = renderApp("/akten/1", summarizeApi({ status: aiStatus }));
    const button = (await screen.findByRole("button", {
      name: "Zusammenfassen",
    })) as HTMLButtonElement;
    await waitFor(() => expect(button.getAttribute("title")).toBe(NO_TEXT_SERVICE));
    expect(button.disabled).toBe(true);
    expect(NO_TEXT_SERVICE).toBe("Kein Textmodell eingerichtet (System › Einstellungen)");
    expect(taskCalls(calls)).toEqual([]);
  });
});
