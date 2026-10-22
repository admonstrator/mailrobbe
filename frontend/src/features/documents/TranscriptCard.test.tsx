import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentDetail, DocumentListItem } from "../../api/types";
import {
  aiStatus,
  documentItems,
  documentPage,
  recordingDocument,
  transcriptResult,
  transcriptView,
  untranscribedDocument,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { TRANSCRIPT_TITLE } from "./MachineMark";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** The fixture backend with these recordings and the AI endpoints their page uses. */
function api(...documents: DocumentDetail[]) {
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    const found = documents.find((document) => path === `/api/documents/${document.id}`);
    if (found) return found;
    if (path === `/api/documents/${recordingDocument.id}/transcript`) return transcriptView;
    if (path === "/api/ai/status") return aiStatus;
    if (path === "/api/ai/tasks") {
      return { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "started" };
    }
    if (path === "/api/ai/results/88/discard") return { changed: 1 };
    return fixtureApi(call);
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);
const card = () => screen.findByRole("region", { name: "Transkript" });
const transcribed = (patch: Partial<DocumentDetail>) => ({ ...recordingDocument, ...patch });

describe("the transcript of a recording", () => {
  it("stands below the player with its lines, instead of the text card", async () => {
    renderApp(`/anhaenge/${recordingDocument.id}`, api(recordingDocument));
    const transcript = await card();
    expect(
      within(transcript).getByText(
        "Maschinell transkribiert · Parakeet v3 · 22.10.2026 · Aufnahme 3:12",
      ),
    ).toBeTruthy();
    expect(within(transcript).getByText("4 Zeilen")).toBeTruthy();
    expect(
      within(transcript).getByText("1 Zeile unsicher erkannt, gepunktet unterstrichen."),
    ).toBeTruthy();
    const list = await within(transcript).findByRole("list", { name: "Zeilen des Transkripts" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(4);
    // Right below the player; the plain text card is not there.
    const preview = screen.getByRole("heading", { name: "Vorschau" }).closest("section")!;
    expect(preview.nextElementSibling).toBe(transcript);
    expect(screen.queryByRole("region", { name: "Ausgelesener Text" })).toBeNull();
    expect(within(transcript).getByRole("button", { name: "Neu transkribieren" })).toBeTruthy();
    expect(within(transcript).queryByRole("button", { name: "Transkribieren" })).toBeNull();
  });

  it("says in the header that the text was heard, and how long the recording is", async () => {
    renderApp(`/anhaenge/${recordingDocument.id}`, api(recordingDocument));
    await screen.findByRole("heading", { level: 1, name: "Sprachnachricht_Vorstand.ogg" });
    expect(screen.getByText("Audio/Video · 3:12 · 96 KB · audio/ogg")).toBeTruthy();
    const mark = screen.getByText("maschinell transkribiert");
    expect(mark.title).toBe(TRANSCRIPT_TITLE);
    expect(screen.getByText("transkribiert 22.10.2026 11:12")).toBeTruthy();
    expect(
      screen.getByText(/aus dem Ton der Aufnahme transkribiert \(siehe „Transkript“\)/),
    ).toBeTruthy();
  });

  it("plays the page's player from a line's time and marks the line playing", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    renderApp(`/anhaenge/${recordingDocument.id}`, api(recordingDocument));
    const transcript = await card();
    const time = await within(transcript).findByRole("button", { name: "Ab 0:06 abspielen" });
    const audio = document.querySelector("audio")!;
    expect(audio.getAttribute("src")).toBe("/api/attachments/960/media");
    fireEvent.click(time);
    expect(audio.currentTime).toBe(6.8);
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.timeUpdate(audio);
    const playing = within(transcript).getByRole("listitem", { current: true });
    expect(playing.textContent).toContain("Die Sitzung mit dem Rat");
  });

  it("says when nobody speaks or the file has no sound", async () => {
    const silent = { ...transcriptResult, segments: 0, uncertain: 0, characters: 0 };
    renderApp(
      `/anhaenge/${recordingDocument.id}`,
      api(transcribed({ transcript: { result: silent, task: null } })),
    );
    const transcript = await card();
    expect(within(transcript).getByText("Keine Sprache erkannt.")).toBeTruthy();
    expect(
      within(transcript).getByText("Maschinell geprüft · Parakeet v3 · 22.10.2026"),
    ).toBeTruthy();
    expect(within(transcript).queryByRole("list")).toBeNull();
  });

  it("says when the file has no sound track", async () => {
    const mute = { ...transcriptResult, segments: 0, uncertain: 0, characters: 0, audio: false };
    renderApp(
      `/anhaenge/${recordingDocument.id}`,
      api(transcribed({ transcript: { result: mute, task: null } })),
    );
    expect(within(await card()).getByText("Die Datei hat keine Tonspur.")).toBeTruthy();
  });

  it("says how far a recording was read when it was cut", async () => {
    const cut = { ...transcriptResult, duration: 14_706, transcribed: 10_800 };
    renderApp(
      `/anhaenge/${recordingDocument.id}`,
      api(transcribed({ transcript: { result: cut, task: null } })),
    );
    expect(
      within(await card()).getByText(
        "Maschinell transkribiert · Parakeet v3 · 22.10.2026 · Aufnahme 4:05:06 · die ersten 180 Minuten von 246",
      ),
    ).toBeTruthy();
  });

  it("transcribes a recording at once and asks again until the run is done", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let state: "none" | "running" | "done" = "none";
    const running = {
      ...untranscribedDocument,
      transcript: { result: null, task: { id: 305, status: "running" as const, seconds_read: 65 } },
    };
    const done = {
      ...untranscribedDocument,
      text_status: "text" as const,
      text_origin: "transcript" as const,
      duration: 192.4,
      transcript: { result: transcriptResult, task: null },
    };
    const { calls } = renderApp(`/anhaenge/${untranscribedDocument.id}`, (call) => {
      if (call.url.pathname === "/api/ai/tasks") state = "running";
      if (call.url.pathname === `/api/documents/${untranscribedDocument.id}/transcript`) {
        return transcriptView;
      }
      const document = { none: untranscribedDocument, running, done }[state];
      return api(document)(call);
    });
    const transcript = await card();
    expect(within(transcript).getByText(/^Noch kein Transkript\./)).toBeTruthy();
    fireEvent.click(within(transcript).getByRole("button", { name: "Transkribieren" }));
    await waitFor(() => expect(posts(calls, "/api/ai/tasks")).toHaveLength(1));
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      document_ids: [untranscribedDocument.id],
      single: true,
      start: true,
      kind: "transcribe",
    });
    expect(
      await within(transcript).findByText(
        "Die Transkription läuft; das Ergebnis erscheint hier, sobald sie fertig ist.",
      ),
    ).toBeTruthy();
    expect(
      await within(transcript).findByText(/^Transkription läuft · 1:05 transkribiert/),
    ).toBeTruthy();
    expect(within(transcript).queryByRole("button", { name: "Transkribieren" })).toBeNull();

    // While the task is open the page asks again every 3 s; the lines come once it is done.
    state = "done";
    await act(() => vi.advanceTimersByTimeAsync(3_100));
    expect(
      await within(transcript).findByRole("list", { name: "Zeilen des Transkripts" }),
    ).toBeTruthy();
    const asked = () =>
      calls.filter((call) => call.url.pathname === `/api/documents/${untranscribedDocument.id}`)
        .length;
    const before = asked();
    await act(() => vi.advanceTimersByTimeAsync(6_500));
    expect(asked()).toBe(before);
  });

  it("says a queued task waits", async () => {
    renderApp(
      `/anhaenge/${recordingDocument.id}`,
      api(
        transcribed({
          transcript: {
            result: transcriptResult,
            task: { id: 306, status: "waiting", seconds_read: 0 },
          },
        }),
      ),
    );
    const transcript = await card();
    expect(within(transcript).getByText(/^Für die Transkription vorgemerkt/)).toBeTruthy();
    expect(within(transcript).getByRole("link", { name: "zur Seite „KI“" })).toBeTruthy();
    expect(within(transcript).queryByRole("button", { name: "Neu transkribieren" })).toBeNull();
  });

  it("transcribes again after a confirmation", async () => {
    const { calls } = renderApp(`/anhaenge/${recordingDocument.id}`, api(recordingDocument));
    fireEvent.click(within(await card()).getByRole("button", { name: "Neu transkribieren" }));
    const dialog = await screen.findByRole("dialog", { name: "Neu transkribieren?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Jetzt transkribieren" }));
    await waitFor(() => expect(posts(calls, "/api/ai/tasks")).toHaveLength(1));
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({
      document_ids: [recordingDocument.id],
      single: true,
      start: true,
      kind: "transcribe",
    });
  });

  it("discards a transcript after a confirmation", async () => {
    const { calls } = renderApp(`/anhaenge/${recordingDocument.id}`, api(recordingDocument));
    const transcript = await card();
    fireEvent.click(within(transcript).getByRole("button", { name: "Verwerfen" }));
    const dialog = await screen.findByRole("dialog", { name: "Transkript verwerfen?" });
    expect(within(dialog).getByText(/Transkript wird aus der Suche genommen/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Verwerfen" }));
    expect(await within(transcript).findByText("Das Transkript ist verworfen.")).toBeTruthy();
    expect(posts(calls, "/api/ai/results/88/discard")).toHaveLength(1);
  });
});

describe("transcripts in the document list", () => {
  it("are marked as transcribed", async () => {
    const heard: DocumentListItem = {
      ...documentItems[0],
      id: 5160,
      name: "Sprachnachricht_Vorstand.ogg",
      text_origin: "transcript",
    };
    renderApp("/anhaenge", (call) =>
      call.url.pathname === "/api/documents"
        ? { ...documentPage, items: [heard, ...documentItems.slice(1)] }
        : fixtureApi(call),
    );
    const row = (await screen.findByRole("link", { name: "Sprachnachricht_Vorstand.ogg" })).closest(
      "tr",
    )!;
    expect(within(row).getByText("transkribiert").title).toBe(TRANSCRIPT_TITLE);
  });
});
