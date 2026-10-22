import { useId, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";

import type { TextParagraph } from "../../api/types";
import { cx } from "../../lib/cx";
import { nextChoice, pendingText, type BlockStanding } from "../blocks/choice";
import { mailsText } from "../blocks/labels";
import { blockPath } from "../blocks/urlState";
import styles from "./ParagraphMenu.module.css";

/** A paragraph of the text view (D224) with its menu at the start: a small handle in the margin
 *  that shows on hover and focus and opens the team's choice (D227). A pending choice keeps the
 *  handle in view and says so after the paragraph, unless the fold around it does already. */
export function MenuParagraph({
  paragraph,
  standing,
  busy,
  failed,
  noted,
  onChoose,
  children,
}: {
  paragraph: TextParagraph;
  standing: BlockStanding;
  busy: boolean;
  failed: boolean;
  noted: boolean;
  onChoose: (standard: boolean) => void;
  children: ReactNode;
}) {
  return (
    <span className={styles.paragraph}>
      <ParagraphMenu
        paragraph={paragraph}
        standing={standing}
        busy={busy}
        failed={failed}
        onChoose={onChoose}
      />
      {children}
      {standing.pending && !noted && <PendingNote expected={standing.expected} />}
    </span>
  );
}

/** "Kein Standardblock · wirkt beim nächsten Lauf" after a paragraph or on a fold's toggle. */
export function PendingNote({ expected }: { expected: boolean }) {
  return <span className={styles.pending}>{pendingText(expected)}</span>;
}

/** The handle and, open, the menu: the one choice the paragraph allows, the way to its block's
 *  page once a run counted it, and when the choice takes effect. Escape and leaving it close it. */
function ParagraphMenu({
  paragraph,
  standing,
  busy,
  failed,
  onChoose,
}: {
  paragraph: TextParagraph;
  standing: BlockStanding;
  busy: boolean;
  failed: boolean;
  onChoose: (standard: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const handle = useRef<HTMLButtonElement>(null);
  const id = useId();
  const choice = nextChoice(standing);

  return (
    <span
      className={styles.anchor}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        event.preventDefault();
        setOpen(false);
        handle.current?.focus();
      }}
    >
      <button
        ref={handle}
        type="button"
        className={cx(styles.handle, open && styles.open, standing.pending && styles.marked)}
        aria-label="Absatz: Standardblock"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        title="Standardblock"
        onClick={() => setOpen(!open)}
      >
        ¶
      </button>
      {open && (
        <span id={id} role="group" aria-label="Absatz" className={styles.menu}>
          <button
            type="button"
            className={styles.item}
            disabled={busy}
            onClick={() => onChoose(choice.standard)}
          >
            {choice.label}
          </button>
          {paragraph.mails > 0 && (
            <Link to={blockPath(paragraph.hash)} className={styles.link}>
              {`In ${mailsText(paragraph.mails)}`}
            </Link>
          )}
          <span className={styles.note}>
            {standing.pending ? pendingText(standing.expected) : "Wirkt beim nächsten Lauf."}
          </span>
          {failed && (
            <span className={styles.error} role="alert">
              Nicht gespeichert.
            </span>
          )}
        </span>
      )}
    </span>
  );
}
