import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiStatus, ServiceCheck } from "../../api/types";
import {
  aiJobRunning,
  aiJobTranscribing,
  aiResultPage,
  aiSendLogPage,
  aiStatus,
  aiStatusRemoteRefused,
  aiStatusRunning,
  aiTaskPage,
  aiTranscription,
} from "../../test/fixtures";
import { fixtureApi, renderApp, renderElement, type ApiCall } from "../../test/render";
import { AiRunLine } from "../import/AiRunLine";

const check: ServiceCheck = {
  capability: "vision",
  url: "http://host.docker.internal:11434",
  locality: "local",
  refused: null,
  reachable: true,
  protocol: "ollama",
  models: [
    { name: "qwen2.5vl:7b", vision: true },
    { name: "llama3.2", vision: false },
  ],
  model: "qwen2.5vl:7b",
  model_found: true,
  test: "passed",
  test_detail: "MAILROBBE 2026",
  seconds: 6.4,
  error: null,
  checked_at: "2026-10-22T08:00:00Z",
};

/** The fixture backend with the AI endpoints; status is the one the test gives. */
function aiApi(status: AiStatus) {
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/ai/status") return status;
    if (path === "/api/ai/tasks" && call.method === "GET") return aiTaskPage;
    if (path === "/api/ai/tasks") return { queued: 214, raised: 2, unreadable: 0, logos: 0 };
    if (path === "/api/ai/tasks/retry" || path === "/api/ai/tasks/cancel") return { changed: 1 };
    if (path === "/api/ai/results") return aiResultPage;
    if (path.endsWith("/discard")) return { changed: 1 };
    if (path === "/api/ai/send-log") return aiSendLogPage;
    if (path === "/api/ai/services/vision/check") return check;
    if (path === "/api/ai/run") return Response.json(aiJobRunning, { status: 202 });
    if (path === "/api/ai/run/stop") return { ...aiJobRunning, stop_requested: true };
    return fixtureApi(call);
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);
const card = (name: string) => screen.getByRole("region", { name });

describe("AI page", () => {
  it("is in the navigation and explains what it does", async () => {
    renderApp("/ki", aiApi(aiStatus));
    expect(await screen.findByRole("heading", { level: 1, name: "KI" })).toBeTruthy();
    expect(document.title).toBe("KI · Mailrobbe");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    expect(within(navigation).getByRole("link", { name: "KI" }).getAttribute("href")).toBe("/ki");
    expect(screen.getByRole("img", { name: /Die KI bewertet nichts/ })).toBeTruthy();
    // The services and work lists come first; the run and the results have tabs of their own.
    const tabs = await screen.findByRole("tablist", { name: "Bereiche der KI" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((tab) => tab.textContent),
    ).toEqual(["Dienste und Arbeitslisten", "Lauf und Warteschlange12", "Ergebnisse"]);
    fireEvent.click(within(tabs).getByRole("tab", { name: "Ergebnisse" }));
    expect(await screen.findByRole("region", { name: "Ergebnisse" })).toBeTruthy();
  });

  it("lists Tesseract and the local service, and tests it", async () => {
    const { calls } = renderApp("/ki", aiApi(aiStatus));
    await screen.findByRole("heading", { name: "Dienste" });
    const services = card("Dienste");
    // Tesseract and the transcriber run in the container.
    expect(within(services).getAllByText("im Container")).toHaveLength(2);
    expect(within(services).getByText("lokal")).toBeTruthy();
    expect(within(services).getByText("http://host.docker.internal:11434")).toBeTruthy();
    expect(within(services).getByText("qwen2.5vl:7b")).toBeTruthy();
    fireEvent.click(within(services).getByRole("button", { name: "Testen" }));
    const result = await within(services).findByRole("status");
    expect(result.textContent).toContain("Erreichbar (Ollama)");
    expect(result.textContent).toContain("Modelle: qwen2.5vl:7b, llama3.2");
    expect(result.textContent).toContain("Test bestanden · 6,4 s");
    expect(result.textContent).toContain("Antwort: MAILROBBE 2026");
    expect(posts(calls, "/api/ai/services/vision/check")).toHaveLength(1);
  });

  it("says why a remote service is refused and how to allow it", async () => {
    renderApp("/ki", aiApi(aiStatusRemoteRefused));
    await screen.findByRole("heading", { name: "Dienste" });
    const services = card("Dienste");
    expect(within(services).getByText("Internet")).toBeTruthy();
    expect(within(services).getByText(/MAILROBBE_AI_ALLOW_REMOTE=true/)).toBeTruthy();
    expect(within(services).getByRole("button", { name: "Testen" })).toHaveProperty(
      "disabled",
      true,
    );
    // Without a usable vision model, Tesseract is the only engine.
    const lists = card("Arbeitslisten");
    const select = within(lists).getByRole("combobox", { name: "Verfahren" });
    expect([...select.querySelectorAll("option")].map((option) => option.textContent)).toEqual([
      "Tesseract",
    ]);
  });

  it("shows the work lists with their estimates and queues one", async () => {
    const { calls } = renderApp("/ki", aiApi(aiStatus));
    await screen.findByRole("heading", { name: "Arbeitslisten" });
    const lists = card("Arbeitslisten");
    const scanned = within(lists).getByRole("region", { name: "Gescannte PDFs" });
    expect(scanned.textContent).toContain("214 Dokumente · 1.380 Seiten (bei 3 unbekannt)");
    expect(scanned.textContent).toContain("geschätzt ca.");
    // Images: nothing to queue.
    const images = within(lists).getByRole("region", { name: "Bilder ab 100 KB" });
    expect(within(images).queryByRole("button", { name: "Vormerken" })).toBeNull();

    fireEvent.change(within(scanned).getByRole("combobox", { name: "Verfahren" }), {
      target: { value: "tesseract" },
    });
    fireEvent.click(within(scanned).getByRole("button", { name: "Vormerken" }));
    expect(
      await within(scanned).findByText("214 Dokumente vorgemerkt, 2 schon vorgemerkt"),
    ).toBeTruthy();
    expect(posts(calls, "/api/ai/tasks").map((call) => call.body)).toEqual([
      { work_list: "scanned", engine: "tesseract" },
    ]);
  });

  it("lists the queue with retry and cancel", async () => {
    const { calls } = renderApp("/ki?tab=lauf", aiApi(aiStatus));
    const queue = await screen.findByRole("region", { name: "Warteschlange" });
    await within(queue).findByRole("link", { name: "Scan_20180306_7499.pdf" });
    expect(within(queue).getByText("service did not answer within 120 s")).toBeTruthy();
    expect(within(queue).getByText("zuerst")).toBeTruthy();

    fireEvent.click(within(queue).getByRole("button", { name: "Erneut" }));
    fireEvent.click(within(queue).getByRole("button", { name: "Abbrechen" }));
    fireEvent.click(
      within(queue).getByRole("button", { name: "Alle fehlgeschlagenen erneut (2)" }),
    );
    await waitFor(() => expect(posts(calls, "/api/ai/tasks/retry")).toHaveLength(2));
    expect(posts(calls, "/api/ai/tasks/retry").map((call) => call.body)).toEqual([
      { ids: [298] },
      { all: true },
    ]);
    expect(posts(calls, "/api/ai/tasks/cancel").map((call) => call.body)).toEqual([{ ids: [301] }]);

    fireEvent.click(within(queue).getByRole("button", { name: "fehlgeschlagen 2" }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/ai/tasks" &&
            call.url.searchParams.getAll("status").join() === "failed",
        ),
      ).toBe(true),
    );
  });

  it("discards a result after a confirmation", async () => {
    const { calls } = renderApp("/ki?tab=ergebnisse", aiApi(aiStatus));
    const results = await screen.findByRole("region", { name: "Ergebnisse" });
    await within(results).findByRole("link", { name: "Scan_20180306_7499.pdf" });
    expect(within(results).getByText("Tesseract und qwen2.5vl:7b")).toBeTruthy();
    expect(within(results).getByText("Nicht gelesen: Seite 3")).toBeTruthy();

    fireEvent.click(within(results).getByRole("button", { name: "ganzen Lauf" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Alle Texte dieses Laufs verwerfen?",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Verwerfen" }));
    expect(await within(dialog).findByText("1 Text verworfen.")).toBeTruthy();
    expect(posts(calls, "/api/ai/jobs/40/discard")).toHaveLength(1);
  });

  it("starts a run with the defaults", async () => {
    const { calls } = renderApp("/ki?tab=lauf", aiApi(aiStatus));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect(within(run).getByText(/12 Dokumente sind vorgemerkt/)).toBeTruthy();
    expect(within(run).getByRole("textbox", { name: "Bildmodell" })).toHaveProperty(
      "value",
      "qwen2.5vl:7b",
    );
    fireEvent.click(within(run).getByRole("button", { name: "KI-Lauf starten" }));
    await waitFor(() => expect(posts(calls, "/api/ai/run")).toHaveLength(1));
    expect(posts(calls, "/api/ai/run")[0].body).toEqual({
      engine: "auto",
      max_pages: 50,
      vision_model: "qwen2.5vl:7b",
      max_minutes: 180,
    });
  });

  it("shows a live run with its pages and steps, and stops it", async () => {
    const { calls } = renderApp("/ki?tab=lauf", aiApi(aiStatusRunning));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect(await within(run).findByText("37 von 120 Seiten")).toBeTruthy();
    expect(within(run).getByText("Scan_20180306_7499.pdf")).toBeTruthy();
    expect(within(run).getByText("Texterkennung")).toBeTruthy();
    fireEvent.click(within(run).getByRole("button", { name: "Anhalten" }));
    await waitFor(() => expect(posts(calls, "/api/ai/run/stop")).toHaveLength(1));
  });

  it("lists what was sent once something went to the internet", async () => {
    renderApp("/ki?tab=ergebnisse", aiApi({ ...aiStatus, remote_used: true }));
    const sent = await screen.findByRole("region", { name: "Gesendet" });
    expect(await within(sent).findByText("https://api.vision.example/v1")).toBeTruthy();
    expect(within(sent).getByText(/1 Sendung\b/)).toBeTruthy();
  });

  it("has no Gesendet card while nothing left the machine", async () => {
    renderApp("/ki?tab=ergebnisse", aiApi(aiStatus));
    await screen.findByRole("region", { name: "Ergebnisse" });
    expect(screen.queryByRole("region", { name: "Gesendet" })).toBeNull();
  });
});

describe("transcription on the AI page (D295)", () => {
  it("describes the transcriber in the container and its files", async () => {
    renderApp("/ki", aiApi(aiStatus));
    await screen.findByRole("heading", { name: "Dienste" });
    const transcriber = within(card("Dienste"))
      .getByText("Parakeet TDT 0.6B v3 (NVIDIA, CC-BY-4.0)")
      .closest("li")!;
    expect(transcriber.textContent).toContain("im Container");
    expect(transcriber.textContent).toContain(
      "auf dem Prozessor (CPU) mit 4 Threads; höchstens 180 Minuten je Aufnahme",
    );
    expect(transcriber.textContent).toContain(
      "Modelldateien werden beim ersten Lauf geladen (641,6 MB).",
    );
  });

  it("says when part of the files or the libraries are missing", async () => {
    renderApp(
      "/ki",
      aiApi({
        ...aiStatus,
        transcription: { ...aiTranscription, missing_bytes: 440_401_920 },
      }),
    );
    await screen.findByRole("heading", { name: "Dienste" });
    expect(
      within(card("Dienste")).getByText(/zu Ende geladen \(noch 420,0 MB von 641,6 MB\)/),
    ).toBeTruthy();
  });

  it("cannot queue recordings without the transcriber's libraries", async () => {
    renderApp(
      "/ki",
      aiApi({ ...aiStatus, transcription: { ...aiTranscription, available: false } }),
    );
    await screen.findByRole("heading", { name: "Dienste" });
    expect(
      within(card("Dienste")).getByText(/Die Bibliotheken der Transkription .* fehlen/),
    ).toBeTruthy();
    const media = within(card("Arbeitslisten")).getByRole("region", {
      name: "Sprachnachrichten und Videos",
    });
    expect(within(media).getByRole("button", { name: "Vormerken" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("lists the recordings with their minutes and queues them without an engine", async () => {
    const { calls } = renderApp("/ki", aiApi(aiStatus));
    await screen.findByRole("heading", { name: "Arbeitslisten" });
    const media = within(card("Arbeitslisten")).getByRole("region", {
      name: "Sprachnachrichten und Videos",
    });
    expect(media.textContent).toContain(
      "38 Dokumente · 162 Minuten (15 ohne bekannte Länge) · 39,3 MB · geschätzt ca. 18 min",
    );
    expect(within(media).queryByRole("combobox")).toBeNull();
    fireEvent.click(within(media).getByRole("button", { name: "Vormerken" }));
    await waitFor(() => expect(posts(calls, "/api/ai/tasks")).toHaveLength(1));
    expect(posts(calls, "/api/ai/tasks")[0].body).toEqual({ work_list: "media" });
  });

  it("names the kind of tasks and results and shows a recording's length", async () => {
    renderApp("/ki?tab=lauf", aiApi(aiStatus));
    const queue = await screen.findByRole("region", { name: "Warteschlange" });
    const task = (
      await within(queue).findByRole("link", { name: "Sprachnachricht_Vorstand.ogg" })
    ).closest("tr")!;
    expect(within(task).getByText("Transkription")).toBeTruthy();
    expect(within(task).getByText("Parakeet v3")).toBeTruthy();
    expect(within(task).getByText("1:05 von 3:12")).toBeTruthy();
    const scan = within(queue).getByRole("link", { name: "Scan_20180306_7499.pdf" }).closest("tr")!;
    expect(within(scan).getByText("Texterkennung")).toBeTruthy();
    expect(within(scan).getByText("0 von 3 Seiten")).toBeTruthy();

    fireEvent.click(screen.getByRole("tab", { name: "Ergebnisse" }));
    const results = await screen.findByRole("region", { name: "Ergebnisse" });
    const result = (
      await within(results).findByRole("link", { name: "Sprachnachricht_Vorstand.ogg" })
    ).closest("tr")!;
    expect(within(result).getByText("4 Zeilen, davon 1 unsicher")).toBeTruthy();
    expect(within(result).getByText("Transkription")).toBeTruthy();
    expect(within(result).getByText("3:12")).toBeTruthy();
    expect(within(result).getByText("312")).toBeTruthy();
    fireEvent.click(within(result).getByRole("button", { name: "Verwerfen" }));
    expect(await screen.findByRole("dialog", { name: "Transkript verwerfen?" })).toBeTruthy();
  });

  it("counts the tasks of both kinds", async () => {
    const queue = {
      ...aiStatus.queue,
      transcribe: { waiting: 3, running: 0, done: 5, failed: 1, cancelled: 0 },
    };
    renderApp("/ki?tab=lauf", aiApi({ ...aiStatus, queue }));
    const tasks = await screen.findByRole("region", { name: "Warteschlange" });
    expect(within(tasks).getByRole("button", { name: "vorgemerkt 15" })).toBeTruthy();
    expect(
      within(tasks).getByRole("button", { name: "Alle fehlgeschlagenen erneut (3)" }),
    ).toBeTruthy();
    expect(within(card("Lauf")).getByText(/15 Dokumente sind vorgemerkt/)).toBeTruthy();
  });

  it("starts a run with the minutes per recording", async () => {
    const { calls } = renderApp("/ki?tab=lauf", aiApi(aiStatus));
    const run = await screen.findByRole("region", { name: "Lauf" });
    const minutes = within(run).getByRole("textbox", { name: "Minuten je Aufnahme" });
    expect(minutes).toHaveProperty("value", "180");
    fireEvent.change(minutes, { target: { value: "30" } });
    fireEvent.click(within(run).getByRole("button", { name: "KI-Lauf starten" }));
    await waitFor(() => expect(posts(calls, "/api/ai/run")).toHaveLength(1));
    expect(posts(calls, "/api/ai/run")[0].body).toMatchObject({ max_minutes: 30 });
  });

  it("shows a run transcribing with its minutes and the place in the recording", async () => {
    renderApp("/ki?tab=lauf", aiApi({ ...aiStatus, job: aiJobTranscribing }));
    const run = await screen.findByRole("region", { name: "Lauf" });
    expect(await within(run).findByText("Transkription")).toBeTruthy();
    expect(run.textContent).toContain("13 Minuten transkribiert");
    expect(run.textContent).toContain("In Arbeit: Sprachnachricht_Vorstand.ogg · 1:05 von 3:12");
  });
});

describe("AI run on the dashboard", () => {
  it("says a run lives, with its pages, and links the page", () => {
    renderElement(<AiRunLine run={aiJobRunning} />);
    const line = screen.getByRole("region", { name: "KI-Lauf" });
    expect(line.textContent).toContain("KI-Lauf läuft · 37 von 120 Seiten");
    expect(line.textContent).toContain("Ein Import kann erst danach starten.");
    expect(within(line).getByRole("link", { name: "Zur Seite „KI“" }).getAttribute("href")).toBe(
      "/ki",
    );
  });

  it("says how many minutes a run transcribed", () => {
    renderElement(<AiRunLine run={aiJobTranscribing} />);
    expect(screen.getByRole("region", { name: "KI-Lauf" }).textContent).toContain(
      "KI-Lauf läuft · 13 Minuten transkribiert · Ein Import",
    );
  });

  it("shows nothing without a live run", () => {
    renderElement(<AiRunLine run={{ ...aiJobRunning, alive: false, status: "done" }} />);
    expect(screen.queryByRole("region", { name: "KI-Lauf" })).toBeNull();
  });
});
