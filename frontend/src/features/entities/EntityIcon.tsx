import type { ReactNode } from "react";

import type { EntityKind } from "../../api/types";
import { KIND_LABELS } from "./labels";

/** One glyph per kind, drawn like components/icons.tsx. */
const GLYPHS: Record<EntityKind, ReactNode> = {
  amount: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <circle cx="12" cy="12" r="2.5" />
      <path d="M6.5 9.5v.01M17.5 14.5v.01" />
    </>
  ),
  iban: (
    <>
      <path d="M3 9l9-5 9 5z" />
      <path d="M5 9v8M9.5 9v8M14.5 9v8M19 9v8M3 20h18" />
    </>
  ),
  account: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 10h4M7 14h10" />
    </>
  ),
  organization: (
    <>
      <path d="M4 21V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v16M15 10h4a1 1 0 0 1 1 1v10M2 21h20" />
      <path d="M8 8h3M8 12h3M8 16h3" />
    </>
  ),
  person: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  place: (
    <>
      <path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </>
  ),
  phone: (
    <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z" />
  ),
  email: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 7l9 6 9-6" />
    </>
  ),
  url: (
    <>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </>
  ),
  domain: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </>
  ),
  date: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </>
  ),
  term: (
    <>
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <path d="M7.5 7.5v.01" />
    </>
  ),
};

/** The marker of an entity's kind. Decorative unless labelled, since a heading or a column
 *  beside it usually names the kind. */
export function EntityIcon({
  kind,
  size = 14,
  labelled = false,
  className,
}: {
  kind: EntityKind;
  size?: number;
  labelled?: boolean;
  className?: string;
}) {
  const label = KIND_LABELS[kind].one;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      style={{ flexShrink: 0 }}
      {...(labelled ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {labelled && <title>{label}</title>}
      {GLYPHS[kind]}
    </svg>
  );
}
