import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { useDocumentTranscript } from "../../api/queries";
import type { TranscriptSegment } from "../../api/types";
import { Button } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import { MarkedParts, markWords, type SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatClock } from "../../lib/format";
import type { TextPart } from "../../lib/highlight";
import { silenceText } from "../ai/labels";
import { MachineMark } from "../documents/MachineMark";
import { AttachmentPreview } from "./AttachmentPreview";
import styles from "./Transcript.module.css";

/** The line playing at a second of the recording: the last one started, -1 before the first. */
export function lineAt(segments: TranscriptSegment[], seconds: number): number {
  let low = 0;
  let high = segments.length - 1;
  let found = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (segments[middle].start <= seconds) {
      found = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return found;
}

/** Where a line stands in the list, and what of the list is in view, in pixels. */
export interface LinePlace {
  top: number;
  height: number;
}
export interface ListView {
  scrollTop: number;
  height: number;
}

/** Where the list scrolls to when the line playing changes, or null to leave it: the new line
 *  comes into view only while the reader follows, that is the line before was still (partly) in
 *  view, or, with none before, the list was not scrolled. A reader who scrolled away keeps their
 *  place (D296). */
export function followTop(
  view: ListView,
  line: LinePlace,
  before: LinePlace | null,
): number | null {
  const bottom = view.scrollTop + view.height;
  if (line.top >= view.scrollTop && line.top + line.height <= bottom) return null;
  const following = before
    ? before.top < bottom && before.top + before.height > view.scrollTop
    : view.scrollTop === 0;
  return following ? Math.max(0, line.top - view.height / 3) : null;
}

/** Plays the player from a second on; a browser that refuses (no sound allowed yet) leaves it
 *  set there. */
function playFrom(player: HTMLMediaElement, seconds: number) {
  player.currentTime = seconds;
  Promise.resolve(player.play()).catch(() => undefined);
}

const place = (element: HTMLElement): LinePlace => ({
  top: element.offsetTop,
  height: element.offsetHeight,
});

/** The index of the line the player is at, asked again only when the player moves: a new line
 *  renders two lines again, not every one per timeupdate. */
function usePlaying(segments: TranscriptSegment[], player: HTMLMediaElement | null): number {
  const [current, setCurrent] = useState(-1);
  useEffect(() => {
    if (!player) return;
    const update = () => setCurrent(lineAt(segments, player.currentTime));
    player.addEventListener("timeupdate", update);
    player.addEventListener("seeked", update);
    return () => {
      player.removeEventListener("timeupdate", update);
      player.removeEventListener("seeked", update);
    };
  }, [segments, player]);
  return current;
}

const NO_PLAYER = "Der Browser kann diese Aufnahme nicht abspielen.";

/** One line: its time as a button that plays from there, its text with the search words. */
const Line = memo(function Line({
  segment,
  parts,
  playing,
  onPlay,
}: {
  segment: TranscriptSegment;
  parts: TextPart[] | undefined;
  playing: boolean;
  onPlay: ((seconds: number) => void) | null;
}) {
  const time = formatClock(segment.start);
  return (
    <li
      className={cx(styles.line, playing && styles.playing, segment.uncertain && styles.uncertain)}
      aria-current={playing ? "true" : undefined}
    >
      <button
        type="button"
        className={styles.time}
        aria-label={`Ab ${time} abspielen`}
        title={onPlay ? undefined : NO_PLAYER}
        disabled={!onPlay}
        onClick={() => onPlay?.(segment.start)}
      >
        {time}
      </button>
      <span className={styles.text} title={segment.uncertain ? "unsicher erkannt" : undefined}>
        {parts ? <MarkedParts parts={parts} /> : segment.text}
        {segment.uncertain && <span className="sr-only"> (unsicher erkannt)</span>}
      </span>
    </li>
  );
});

/** A transcript's lines (D296), each with its time (m:ss, h:mm:ss from an hour on): a click on a
 *  time plays the player from there, the line playing is marked and kept in view while the
 *  reader follows, uncertain lines are marked. With marks, the search words of the mail list are
 *  marked and the first line holding one is scrolled into view. The lines scroll inside the
 *  list, so the page and the player stay where they are. */
export function TranscriptLines({
  segments,
  player,
  marks,
  className,
}: {
  segments: TranscriptSegment[];
  player: HTMLMediaElement | null;
  marks?: SearchMarks;
  className?: string;
}) {
  const list = useRef<HTMLOListElement>(null);
  const before = useRef(-1);
  const current = usePlaying(segments, player);
  const parts = useMemo(
    () => (marks ? segments.map((segment) => markWords(segment.text, marks)) : undefined),
    [segments, marks],
  );
  const play = useCallback((seconds: number) => player && playFrom(player, seconds), [player]);

  // The first line holding a search word in view, within the list.
  useEffect(() => {
    const box = list.current;
    const first = parts ? parts.findIndex((line) => line.some((part) => part.mark)) : -1;
    const line = box?.children[first];
    if (!box || !(line instanceof HTMLElement)) return;
    box.scrollTop = Math.max(0, line.offsetTop - box.clientHeight / 3);
  }, [parts]);

  // The new line playing in view while the reader follows.
  useEffect(() => {
    const box = list.current;
    const previous = box?.children[before.current];
    before.current = current;
    const line = box?.children[current];
    if (!box || !(line instanceof HTMLElement)) return;
    const top = followTop(
      { scrollTop: box.scrollTop, height: box.clientHeight },
      place(line),
      previous instanceof HTMLElement ? place(previous) : null,
    );
    if (top !== null) box.scrollTop = top;
  }, [current]);

  const long = (segments.at(-1)?.start ?? 0) >= 3600;
  return (
    <ol
      ref={list}
      className={cx(styles.lines, long && styles.long, className)}
      aria-label="Zeilen des Transkripts"
    >
      {segments.map((segment, index) => (
        <Line
          key={index}
          segment={segment}
          parts={parts?.[index]}
          playing={index === current}
          onPlay={player ? play : null}
        />
      ))}
    </ol>
  );
}

/** A document's transcript as the API serves it (D296): loading, an error, "Keine Sprache
 *  erkannt." or "Die Datei hat keine Tonspur." without lines, else the lines. result names the
 *  result the page shows, so a new one is loaded once there is one. */
export function Transcript({
  documentId,
  result = null,
  player,
  marks,
  className,
}: {
  documentId: number;
  result?: number | null;
  player: HTMLMediaElement | null;
  marks?: SearchMarks;
  className?: string;
}) {
  const view = useDocumentTranscript(documentId, true, result);
  if (view.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Transkript wird geladen" />
      </div>
    );
  }
  if (view.isError) {
    const gone = view.error instanceof ApiError && view.error.code === "not_found";
    return (
      <ErrorState
        title={
          gone
            ? "Zu dieser Aufnahme gibt es kein Transkript mehr."
            : "Das Transkript konnte nicht geladen werden."
        }
        actions={!gone && <Button onClick={() => void view.refetch()}>Erneut versuchen</Button>}
      >
        {gone
          ? "Es wurde inzwischen verworfen."
          : "Der Server ist nicht erreichbar oder hat einen Fehler gemeldet."}
      </ErrorState>
    );
  }
  if (view.data.segments.length === 0) {
    return <p className={styles.empty}>{silenceText(view.data.result)}</p>;
  }
  return (
    <TranscriptLines
      segments={view.data.segments}
      player={player}
      marks={marks}
      className={className}
    />
  );
}

/** An audio or video attachment over the page with its transcript below the player (D296): the
 *  same lines as on the document page, the mail list's search words marked. */
export function MediaWithTranscript({
  attachmentId,
  kind,
  name,
  documentId,
  marks,
}: {
  attachmentId: number;
  kind: "audio" | "video";
  name: string;
  documentId: number;
  marks?: SearchMarks;
}) {
  const [player, setPlayer] = useState<HTMLMediaElement | null>(null);
  return (
    <div className={styles.withPlayer}>
      <AttachmentPreview
        attachmentId={attachmentId}
        kind={kind}
        name={name}
        fill
        onMedia={setPlayer}
      />
      <p className={styles.heading}>
        Transkript <MachineMark transcript />
      </p>
      <Transcript
        documentId={documentId}
        player={player}
        marks={marks}
        className={kind === "video" ? styles.belowVideo : styles.belowAudio}
      />
    </div>
  );
}
