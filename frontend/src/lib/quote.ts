// Splitting the quoted history off the end of a mail's text, so the detail view can collapse it.

export interface QuoteSplit {
  /** The mail's own text, trailing blank lines removed. */
  body: string;
  /** The quoted history from its first line to the last non-blank line of the mail. */
  quoted: string;
  quotedLines: number;
}

const ATTRIBUTION = /^(Am\s.+\sschrieb\b.*|On\s.+\swrote):$/;
const SEPARATOR = /^-{2,}\s*(Ursprüngliche Nachricht|Original Message)\s*-{2,}$/i;
const HEADER_FROM = /^\*?(Von|From):/;
const HEADER_SENT = /^\*?(Gesendet|Sent):/;

const isBlank = (line: string) => line.trim() === "";
const isQuoted = (line: string) => /^\s*>/.test(line);

/** Lines an attribution such as "Am 17.10.2026 um 09:05 schrieb Jonas Brandt:" or "On … wrote:"
 *  takes from line i on: 0 when there is none, 2 when a mail client wrapped it. */
function attributionLength(lines: string[], i: number): number {
  const line = lines[i]?.trim() ?? "";
  if (ATTRIBUTION.test(line)) return 1;
  const next = lines[i + 1]?.trim() ?? "";
  return next && ATTRIBUTION.test(`${line} ${next}`) ? 2 : 0;
}

/** An Outlook-style start of the original message: a separator line, or "Von:" followed within
 *  three lines by "Gesendet:" (also in English). */
function startsOriginal(lines: string[], i: number): boolean {
  const line = lines[i].trim();
  if (SEPARATOR.test(line)) return true;
  if (!HEADER_FROM.test(line)) return false;
  return lines.slice(i + 1, i + 4).some((next) => HEADER_SENT.test(next.trim()));
}

/** The quoted history at the end of text, or null when there is none or nothing precedes it.
 *  It starts at the first of: an Outlook-style original message (everything after it belongs to
 *  the history), or the trailing run of ">" lines together with the attribution above it. */
export function splitQuoted(text: string): QuoteSplit | null {
  const lines = text.split(/\r?\n/);
  let end = lines.length;
  while (end > 0 && isBlank(lines[end - 1])) end--;

  let start = lines.findIndex((_, i) => i < end && startsOriginal(lines, i));
  if (start < 0) start = end;

  let block = end;
  while (block > 0 && (isQuoted(lines[block - 1]) || isBlank(lines[block - 1]))) block--;
  while (block < end && isBlank(lines[block])) block++;
  if (block < end) {
    let above = block - 1;
    while (above >= 0 && isBlank(lines[above])) above--;
    if (attributionLength(lines, above) === 1) block = above;
    else if (attributionLength(lines, above - 1) === 2) block = above - 1;
    start = Math.min(start, block);
  }

  const body = lines.slice(0, start).join("\n").trimEnd();
  if (start >= end || !body.trim()) return null;
  return { body, quoted: lines.slice(start, end).join("\n"), quotedLines: end - start };
}
