import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TranscriptSegment } from "../../api/types";
import { transcriptSegments } from "../../test/fixtures";
import { renderElement } from "../../test/render";
import { followTop, lineAt, TranscriptLines } from "./Transcript";

afterEach(() => vi.restoreAllMocks());

/** Lines 30 px high one below the other, in a list showing 60 px: jsdom lays nothing out. */
function stubLayout() {
  vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (
    this: HTMLElement,
  ) {
    return this.tagName === "LI" ? [...this.parentElement!.children].indexOf(this) * 30 : 0;
  });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(30);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(60);
}

/** A player of its own, as the preview card's <audio> would be; play only records. */
function player() {
  const audio = document.createElement("audio");
  const play = vi.spyOn(audio, "play").mockResolvedValue(undefined);
  return { audio, play };
}

const lines = () => screen.getByRole("list", { name: "Zeilen des Transkripts" });
const line = (index: number) => within(lines()).getAllByRole("listitem")[index];

/** Moves the player to a second, as playing or the scrubber does. */
function moveTo(audio: HTMLAudioElement, seconds: number) {
  audio.currentTime = seconds;
  fireEvent.timeUpdate(audio);
}

describe("the line playing", () => {
  it("is the last line started, none before the first", () => {
    expect(lineAt(transcriptSegments, 0)).toBe(-1);
    expect(lineAt(transcriptSegments, 0.4)).toBe(0);
    // In the pause after a line it stays marked.
    expect(lineAt(transcriptSegments, 14.9)).toBe(1);
    expect(lineAt(transcriptSegments, 15)).toBe(2);
    expect(lineAt(transcriptSegments, 600)).toBe(3);
    expect(lineAt([], 5)).toBe(-1);
  });

  it("comes into view only while the reader follows", () => {
    const view = { scrollTop: 0, height: 90 };
    const at = (top: number) => ({ top, height: 20 });
    // In view already: nothing to do.
    expect(followTop(view, at(40), at(20))).toBeNull();
    // Below, while the line before is still in view: a third from the top.
    expect(followTop(view, at(100), at(80))).toBe(70);
    // The reader scrolled away from the line before: the list stays.
    expect(followTop({ scrollTop: 400, height: 90 }, at(100), at(80))).toBeNull();
    // Nothing before: followed only from a list nobody scrolled.
    expect(followTop(view, at(300), null)).toBe(270);
    expect(followTop({ scrollTop: 200, height: 90 }, at(20), null)).toBeNull();
  });
});

describe("transcript lines", () => {
  it("show each line with its time, the uncertain ones marked", () => {
    const { audio } = player();
    renderElement(<TranscriptLines segments={transcriptSegments} player={audio} />);
    expect(
      within(lines())
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["0:00", "0:06", "0:15", "1:05"]);
    expect(line(1).textContent).toContain(
      "Die Sitzung mit dem Rat wird auf Donnerstag verschoben.",
    );
    // Heard with little certainty: marked, and said to a screen reader.
    expect(within(line(2)).getByTitle("unsicher erkannt").textContent).toBe(
      "Die Spende aus Leipzig ist noch nicht gebucht. (unsicher erkannt)",
    );
    expect(within(line(1)).queryByTitle("unsicher erkannt")).toBeNull();
  });

  it("write times beyond an hour with hours", () => {
    const long: TranscriptSegment[] = [
      { start: 3_599, end: 3_605, text: "Kurz vor der Stunde.", confidence: 0.9, uncertain: false },
      { start: 3_725, end: 3_731, text: "Danach.", confidence: 0.9, uncertain: false },
    ];
    renderElement(<TranscriptLines segments={long} player={null} />);
    expect(screen.getByRole("button", { name: "Ab 59:59 abspielen" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ab 1:02:05 abspielen" })).toBeTruthy();
  });

  it("play the player from a line's time and mark the line playing", () => {
    const { audio, play } = player();
    renderElement(<TranscriptLines segments={transcriptSegments} player={audio} />);
    expect(within(lines()).queryAllByRole("listitem", { current: true })).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Ab 1:05 abspielen" }));
    expect(audio.currentTime).toBe(65.3);
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.timeUpdate(audio);
    expect(line(3).getAttribute("aria-current")).toBe("true");

    moveTo(audio, 16);
    expect(line(2).getAttribute("aria-current")).toBe("true");
    expect(line(3).hasAttribute("aria-current")).toBe(false);
  });

  it("cannot play without a player", () => {
    renderElement(<TranscriptLines segments={transcriptSegments} player={null} />);
    const time = screen.getByRole("button", { name: "Ab 0:06 abspielen" });
    expect(time).toHaveProperty("disabled", true);
    expect(time.title).toBe("Der Browser kann diese Aufnahme nicht abspielen.");
  });

  it("keep the line playing in view only while the reader follows", () => {
    stubLayout();
    const { audio } = player();
    renderElement(<TranscriptLines segments={transcriptSegments} player={audio} />);
    const list = lines();
    moveTo(audio, 1);
    expect(list.scrollTop).toBe(0);
    // The third line is below the 60 px in view; the first was in view, so the list follows.
    moveTo(audio, 16);
    expect(list.scrollTop).toBe(40);
    // The reader scrolls back up, away from the line playing: the next line leaves the list.
    list.scrollTop = 0;
    moveTo(audio, 66);
    expect(list.scrollTop).toBe(0);
    expect(line(3).getAttribute("aria-current")).toBe("true");
  });

  it("mark the search words and show the first line holding one", () => {
    stubLayout();
    renderElement(
      <TranscriptLines
        segments={transcriptSegments}
        player={null}
        marks={{ words: ["Rat"], stems: [], whole_word: true }}
      />,
    );
    const marked = lines().querySelectorAll("mark");
    expect([...marked].map((mark) => mark.textContent)).toEqual(["Rat", "Rat"]);
    expect(line(1).contains(marked[0])).toBe(true);
    // The second line, 30 px down, a third of the list from its top.
    expect(lines().scrollTop).toBe(10);
  });
});
