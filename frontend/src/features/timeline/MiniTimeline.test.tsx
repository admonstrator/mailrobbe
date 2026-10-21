import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../api/queries";
import type { Timeline } from "../../api/types";
import { timelineAll, timelineAnna } from "../../test/fixtures";
import { MiniTimeline } from "./MiniTimeline";
import styles from "./MiniTimeline.module.css";

/** 36 months of 10 px each: month i lies from 10 i to 10 i + 10. */
const WIDTH = 360;

function renderTimeline(
  answer: Timeline | Response | null,
  props: Partial<ComponentProps<typeof MiniTimeline>> = {},
) {
  const onPick = vi.fn();
  const fetch = vi.fn((input: RequestInfo | URL) => {
    void input;
    if (answer === null) return new Promise<Response>(() => {}); // still counting
    return Promise.resolve(answer instanceof Response ? answer : Response.json(answer));
  });
  vi.stubGlobal("fetch", fetch);
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retry: false } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MiniTimeline filters={{}} onPick={onPick} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onPick, fetch };
}

/** The chart, laid out WIDTH px wide as jsdom lays out nothing. */
async function chart(): Promise<HTMLElement> {
  const slider = await screen.findByRole("slider");
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, WIDTH, 80));
  return slider;
}

const tip = (slider: HTMLElement) => slider.getAttribute("aria-valuetext");

describe("compact timeline", () => {
  it("draws a bar per bucket with the scale, the ends of the axis and the marks", async () => {
    const { fetch } = renderTimeline(timelineAll, { filters: { q: "Spende", person: [11] } });
    const slider = await chart();
    expect(slider.getAttribute("aria-label")).toBe("Mails pro Monat");
    expect(screen.getByRole("heading", { name: "Verlauf pro Monat" })).toBeTruthy();
    expect(String(fetch.mock.calls[0][0])).toBe("/api/timeline?q=Spende&person=11");

    const bars = [...slider.querySelectorAll("g > rect")];
    expect(bars).toHaveLength(36);
    // March 2024 is the largest count and far above the moving mean: the full height, marked.
    expect(bars[14].getAttribute("height")).toBe("38");
    expect(bars[14].classList.contains(styles.high)).toBe(true);
    expect(bars[13].classList.contains(styles.high)).toBe(false);
    expect(bars[26].classList.contains(styles.high)).toBe(false);
    const marks = [...slider.querySelectorAll("use[data-mark]")];
    expect(marks.map((mark) => [mark.getAttribute("data-mark"), mark.getAttribute("x")])).toEqual([
      ["high", `${14.5 * (100 / 36)}%`],
      ["low", `${26.5 * (100 / 36)}%`],
    ]);
    // ▲ filled above the bar, ▽ hollow under the axis.
    expect(marks[0].classList.contains(styles.up)).toBe(true);
    expect(marks[0].getAttribute("y")).toBe("8");
    expect(marks[1].classList.contains(styles.down)).toBe(true);
    expect(marks[1].getAttribute("y")).toBe("50");

    expect(screen.getByText("4.300")).toBeTruthy();
    expect(screen.getByText("Januar 2023")).toBeTruthy();
    expect(screen.getByText("Dezember 2025")).toBeTruthy();
    expect(screen.getByText("viel mehr als üblich")).toBeTruthy();
    expect(screen.getByText("viel weniger als üblich")).toBeTruthy();
    expect(screen.getByText("214 Mails ohne Datum")).toBeTruthy();
    expect(screen.queryByText(/verstummt/)).toBeNull();
    expect(screen.getByRole("link", { name: "Zeitachse öffnen" }).getAttribute("href")).toBe(
      "/zeitachse?q=Spende&person=11",
    );
  });

  it("names the bucket under the pointer or the keyboard, with the usual count", async () => {
    renderTimeline(timelineAll);
    const slider = await chart();

    fireEvent.pointerMove(slider, { clientX: 145 });
    const text = "März 2024: 4.300 Mails · üblich etwa 1.216";
    expect(screen.getByText(text)).toBeTruthy();
    expect(tip(slider)).toBe(text);
    fireEvent.pointerMove(slider, { clientX: 3 });
    expect(screen.getByText("Januar 2023: 1.100 Mails")).toBeTruthy();
    fireEvent.pointerLeave(slider);
    expect(screen.queryByText("Januar 2023: 1.100 Mails")).toBeNull();

    fireEvent.focus(slider);
    expect(tip(slider)).toBe("Dezember 2025: 1.100 Mails");
    for (let step = 0; step < 9; step += 1) fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(tip(slider)).toBe("März 2025: 240 Mails · üblich etwa 1.180");
    expect(slider.getAttribute("aria-valuenow")).toBe("26");
    fireEvent.keyDown(slider, { key: "Home" });
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(tip(slider)).toBe("Januar 2023: 1.100 Mails");
    fireEvent.keyDown(slider, { key: "End" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(slider.getAttribute("aria-valuenow")).toBe("35");
  });

  it("hands a clicked or entered bucket's days within the Zeitraum to the parent", async () => {
    const { onPick } = renderTimeline(timelineAll, { filters: { date_to: "2024-03-20" } });
    const slider = await chart();

    fireEvent.click(slider, { clientX: 147 });
    expect(onPick).toHaveBeenLastCalledWith({ date_from: "2024-03-01", date_to: "2024-03-20" });

    fireEvent.focus(slider);
    fireEvent.keyDown(slider, { key: "Home" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    fireEvent.keyDown(slider, { key: "Enter" });
    expect(onPick).toHaveBeenLastCalledWith({ date_from: "2023-02-01", date_to: "2023-02-28" });
    expect(onPick).toHaveBeenCalledTimes(2);
  });

  it("hatches a silence from its first bucket on and says it in words when asked", async () => {
    renderTimeline(timelineAnna, {
      filters: { person: [11], hide_duplicates: true },
      bucket: "month",
      silenceLine: true,
    });
    const slider = await chart();
    const band = slider.querySelector("[data-mark=silent]")!;
    expect(band.getAttribute("x")).toBe(`${33 * (100 / 36)}%`);
    expect(band.getAttribute("width")).toBe(`${3 * (100 / 36)}%`);
    expect(screen.getByText("Seit Oktober 2025 keine Mails mehr")).toBeTruthy();
    expect(screen.getByText(/verstummt seit Oktober 2025/)).toBeTruthy();
    expect(screen.getByText("3 Mails ohne Datum")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zeitachse öffnen" }).getAttribute("href")).toBe(
      "/zeitachse?person=11&hide_duplicates=true&bucket=month",
    );
  });

  it("marks a silence only on the axis without silenceLine", async () => {
    renderTimeline(timelineAnna);
    await chart();
    expect(screen.getByText(/verstummt seit Oktober 2025/)).toBeTruthy();
    expect(screen.queryByText("Seit Oktober 2025 keine Mails mehr")).toBeNull();
  });

  it("says in one line that the count ran out of time", async () => {
    renderTimeline({ ...timelineAll, total: null, undated: null, timed_out: true });
    expect(await screen.findByText("Zeitachse: Zählung dauerte zu lange")).toBeTruthy();
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.getByRole("link", { name: "Zeitachse öffnen" })).toBeTruthy();
  });

  it("says in one line that no matching mail has a date", async () => {
    const empty = { ...timelineAnna.total!, counts: [], total: 0, silent_from: null };
    renderTimeline({ ...timelineAll, starts: [], total: empty, undated: 5 });
    expect(
      await screen.findByText("Zeitachse: keine datierten Mails · 5 Mails ohne Datum"),
    ).toBeTruthy();
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("notes a coarser bucket than asked for", async () => {
    renderTimeline({ ...timelineAll, coarsened: true });
    expect(await screen.findByText("gröber eingeteilt, sonst über 1.500 Balken")).toBeTruthy();
  });

  it("says so when the timeline cannot be loaded", async () => {
    renderTimeline(Response.json({ detail: "boom" }, { status: 500 }));
    expect(await screen.findByText("Die Zeitachse konnte nicht geladen werden.")).toBeTruthy();
  });

  it("keeps a quiet placeholder of the chart's height while counting", () => {
    renderTimeline(null);
    expect(screen.getByLabelText("Zeitachse wird geladen").getAttribute("aria-busy")).toBe("true");
    expect(screen.getByRole("heading", { name: "Verlauf" })).toBeTruthy();
  });
});
