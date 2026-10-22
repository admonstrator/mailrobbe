// The team's choice about a paragraph (D225), shared by the block page and the paragraph menu
// of the mail detail: which button it offers, and the editor's name asked for once (D54).

import { useState, type ReactNode } from "react";

import type { BlockInfo, TextParagraph } from "../../api/types";
import { EditorDialog } from "../../components/EditorDialog";
import { getEditor } from "../../lib/editor";

export const PENDING_TEXT = "wirkt beim nächsten Lauf";

/** Where a paragraph stands: what the next run applies, whether that differs from what the
 *  last run applied, and whether it is a standard block the team can take back again. */
export interface BlockStanding {
  expected: boolean;
  pending: boolean;
  back: boolean; // standard now or detected: "Wieder als Standardblock" rather than marking it
}

/** A block as the API answers it: the team's choice, else detection (D225). */
export function blockStanding(block: BlockInfo): BlockStanding {
  return {
    expected: block.override ?? block.detected,
    pending: block.pending,
    back: block.detected,
  };
}

/** A paragraph as the text view lists it; it does not tell whether detection found it, so a
 *  standard one counts as found. */
export function paragraphStanding(paragraph: TextParagraph): BlockStanding {
  const { override, standard } = paragraph;
  return {
    expected: override ?? standard,
    pending: override !== null && override !== standard,
    back: standard,
  };
}

/** The button the paragraph gets, and the choice it sends. */
export function nextChoice({ expected, back }: BlockStanding): {
  label: string;
  standard: boolean;
} {
  if (expected) return { label: "Kein Standardblock", standard: false };
  return {
    label: back ? "Wieder als Standardblock" : "Als Standardblock markieren",
    standard: true,
  };
}

/** What a pending choice does, for its note. */
export function pendingText(expected: boolean): string {
  return `${expected ? "Als Standardblock markiert" : "Kein Standardblock"} · ${PENDING_TEXT}`;
}

/** Runs a write at once when the editor's name is set or was asked for in this view already;
 *  otherwise asks for it first and then runs it, named or not (D54). */
export function useEditorOnce(): { run: (write: () => void) => void; dialog: ReactNode } {
  const [asked, setAsked] = useState(false);
  const [waiting, setWaiting] = useState<(() => void) | null>(null);
  const run = (write: () => void) => {
    if (asked || getEditor()) {
      write();
      return;
    }
    setAsked(true);
    setWaiting(() => write);
  };
  const dialog = waiting && (
    <EditorDialog
      onClose={() => {
        setWaiting(null);
        waiting();
      }}
    />
  );
  return { run, dialog };
}
