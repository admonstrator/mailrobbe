import type { MailHitCounts } from "../../api/types";
import { formatNumber } from "../../lib/format";

/** The places of MailHitCounts as a row names them, and in its title. */
const HIT_PLACES: readonly [keyof MailHitCounts, string, string][] = [
  ["subject", "Betreff", "im Betreff"],
  ["body", "Text", "im Mailtext"],
  ["attachment", "Anhang", "im Text von Anhängen"],
  ["filename", "Dateiname", "in Dateinamen"],
];

/** Why a mail matched (D176): how often the search words occur where, places without any left
 *  out, so a mail found only through a file name says so. Null when none is counted. */
export function hitPlaces(hits: MailHitCounts): { label: string; title: string } | null {
  const places = HIT_PLACES.filter(([key]) => hits[key] > 0);
  if (places.length === 0) return null;
  return {
    label: places.map(([key, label]) => `${label} ${formatNumber(hits[key])}`).join(" · "),
    title: `Suchwörter: ${places.map(([key, , long]) => `${formatNumber(hits[key])} ${long}`).join(", ")}`,
  };
}
