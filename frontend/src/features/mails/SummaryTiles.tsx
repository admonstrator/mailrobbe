import type { MailSummary } from "../../api/types";
import { formatNumber } from "../../lib/format";

/** "1.207", "mehr als 10.000" for a lower bound, "–" when unknown; never 0 for unknown. */
export function formatTotal(summary: MailSummary): string {
  if (summary.total === null) return "–";
  return summary.exact ? formatNumber(summary.total) : `mehr als ${formatNumber(summary.total)}`;
}
