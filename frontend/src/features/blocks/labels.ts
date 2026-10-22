import { formatNumber } from "../../lib/format";

export const mailsText = (count: number) =>
  `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`;

/** The first lines of a sample that say something, without quote markers, for a list. */
export function firstLines(sample: string, count = 3): string {
  return sample
    .split("\n")
    .map((line) => line.replace(/^\s*(?:>\s?)+/, "").trim())
    .filter(Boolean)
    .slice(0, count)
    .join("\n");
}
