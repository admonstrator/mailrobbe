// Shared vocabulary of the research file (D55 to D61): review labels, tag colours, permalinks.

import { PERMALINK_DIGITS, type ReviewKey, type ReviewStatus, type TagColor } from "../api/types";

export const REVIEW_STATUSES: readonly ReviewStatus[] = ["seen", "relevant", "irrelevant"];
export const REVIEW_KEYS: readonly ReviewKey[] = ["unreviewed", ...REVIEW_STATUSES];

export const REVIEW_LABELS: Record<ReviewKey, string> = {
  unreviewed: "Ungesichtet",
  seen: "Gesichtet",
  relevant: "Relevant",
  irrelevant: "Nicht relevant",
};

export const TAG_COLORS: readonly TagColor[] = [
  "blue",
  "teal",
  "green",
  "amber",
  "red",
  "pink",
  "violet",
  "gray",
];

/** Background, text and border of a tag chip; text on background is at least 4.5:1. */
export const TAG_PALETTE: Record<TagColor, { background: string; text: string; border: string }> = {
  blue: { background: "#E8EFFC", text: "#1D4FB8", border: "#C5D6F6" },
  teal: { background: "#E3F5F3", text: "#0F6B63", border: "#B9E3DE" },
  green: { background: "#E6F6EA", text: "#166534", border: "#BFE6C9" },
  amber: { background: "#FDF3E1", text: "#8A4B08", border: "#F5D9A6" },
  red: { background: "#FDECEC", text: "#B42318", border: "#F6C6C2" },
  pink: { background: "#FCEAF3", text: "#A61E62", border: "#F3C1DA" },
  violet: { background: "#F0EBFD", text: "#5B34C4", border: "#D6CAF7" },
  gray: { background: "#EEF0F3", text: "#4B5260", border: "#D7DBE1" },
};

export const TAG_COLOR_LABELS: Record<TagColor, string> = {
  blue: "Blau",
  teal: "Petrol",
  green: "Grün",
  amber: "Ocker",
  red: "Rot",
  pink: "Pink",
  violet: "Violett",
  gray: "Grau",
};

/** The app path that opens a mail by its content in any Mailrobbe with the same archive (D61). */
export function permalinkPath(rawSha256: string): string {
  return `/m/${rawSha256.slice(0, PERMALINK_DIGITS)}`;
}
