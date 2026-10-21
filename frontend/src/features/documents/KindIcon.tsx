import type { ReactNode } from "react";

import type { DocumentKind } from "../../api/types";
import { cx } from "../../lib/cx";
import styles from "./KindIcon.module.css";
import { KIND_LABELS } from "./labels";

const FILE = (
  <>
    <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
    <path d="M14 3v6h6" />
  </>
);

/** One glyph per kind: a page with its kind's marks, or the thing itself. */
const GLYPHS: Record<DocumentKind, ReactNode> = {
  pdf: (
    <>
      {FILE}
      <path d="M8 13h8M8 17h5" />
    </>
  ),
  document: (
    <>
      {FILE}
      <path d="M8 12h8M8 15h8M8 18h5" />
    </>
  ),
  spreadsheet: (
    <>
      {FILE}
      <path d="M8 12h8v6H8zM12 12v6M8 15h8" />
    </>
  ),
  presentation: (
    <>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M12 16v4M8 20h8M8 12V9M12 12V8M16 12v-2" />
    </>
  ),
  text: (
    <>
      {FILE}
      <path d="M8 13h8M8 17h8" />
    </>
  ),
  email: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="9" cy="10" r="2" />
      <path d="M21 16l-5-5L5 20" />
    </>
  ),
  archive: (
    <>
      <path d="M3 8h18v12H3zM5 4h14l2 4H3z" />
      <path d="M10 12h4" />
    </>
  ),
  media: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M10 9l5 3-5 3z" />
    </>
  ),
  other: FILE,
};

/** The icon of a document's kind, coloured by kind; null (not classified yet) draws a plain page.
 *  Decorative unless labelled, since a label or column beside it names the kind. */
export function KindIcon({
  kind,
  size = 20,
  labelled = false,
  className,
}: {
  kind: DocumentKind | null;
  size?: number;
  labelled?: boolean;
  className?: string;
}) {
  const shown = kind ?? "other";
  const label = kind ? KIND_LABELS[kind] : "Art unbekannt";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cx(styles.icon, styles[shown], className)}
      {...(labelled ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {labelled && <title>{label}</title>}
      {GLYPHS[shown]}
    </svg>
  );
}
