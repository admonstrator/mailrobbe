import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import { useBulkChange, useResearch } from "../../api/queries";
import {
  BULK_LIMIT,
  type BulkRequest,
  type BulkResult,
  type MailSelection,
  type MailSummary,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { REVIEW_KEYS, REVIEW_LABELS, TAG_PALETTE } from "../../lib/research";
import styles from "./BulkBar.module.css";

/** Matches above which "Alle Treffer auswählen" asks first. */
const CONFIRM_ABOVE = 1_000;

type BulkChange = Omit<BulkRequest, keyof MailSelection>;

function bulkErrorText(error: Error): string {
  if (error instanceof ApiError) {
    if (error.code === "too_many_mails") {
      return `Zu viele Mails: Eine Änderung erfasst höchstens ${formatNumber(BULK_LIMIT)}. Bitte die Suche eingrenzen.`;
    }
    if (error.code === "empty_selection") return "Keine der ausgewählten Mails ist noch im Archiv.";
    if (error.code === "not_found") return "Dieses Schlagwort oder diese Akte gibt es nicht mehr.";
  }
  return "Die Änderung ist fehlgeschlagen. Bitte noch einmal versuchen.";
}

/** "1.207 Treffer", "Treffer (mehr als 10.000)" for a lower bound, "Treffer" when unknown. */
function matches(summary: MailSummary | undefined): string {
  if (!summary || summary.total === null) return "Treffer";
  const count = formatNumber(summary.total);
  return summary.exact ? `${count} Treffer` : `Treffer (mehr als ${count})`;
}

/** The bar above the mail table while mails are selected (D60): how many, every match instead
 *  of this page's, and the changes for all of them in one request. */
export function BulkBar({
  selected,
  all,
  summary,
  selection,
  onSelectAll,
  onClear,
  onDone,
  onExport,
}: {
  /** Mails checked on this page. */
  selected: number;
  /** Every match of the filters is selected, not just this page's. */
  all: boolean;
  summary: MailSummary | undefined;
  selection: MailSelection;
  onSelectAll: () => void;
  onClear: () => void;
  onDone: (result: BulkResult) => void;
  onExport: () => void;
}) {
  const bulk = useBulkChange();
  const research = useResearch();
  const tags = research.data?.tags ?? [];
  const collections = research.data?.collections ?? [];
  const busy = bulk.isPending;

  function run(change: BulkChange) {
    bulk.mutate({ ...selection, ...change }, { onSuccess: onDone });
  }

  return (
    <div className={styles.bar} role="region" aria-label="Auswahl">
      <span
        className={styles.count}
        title="Die Auswahl gilt für diese Ansicht: Sie wird zurückgesetzt, wenn sich Filter, Suche, Sortierung oder Seite ändern."
      >
        {all ? `Alle ${matches(summary)} ausgewählt` : `${formatNumber(selected)} ausgewählt`}
      </span>
      {!all && summary && (
        <SelectAll selected={selected} summary={summary} onSelectAll={onSelectAll} />
      )}
      <div className={styles.actions}>
        <Menu label="Schlagwort" disabled={busy}>
          {tags.length === 0 && <p className={styles.empty}>Noch keine Schlagwörter.</p>}
          {tags.map((tag) => (
            <MenuRow
              key={tag.id}
              name={tag.name}
              color={TAG_PALETTE[tag.color].text}
              addLabel={`Schlagwort „${tag.name}“ hinzufügen`}
              removeLabel={`Schlagwort „${tag.name}“ entfernen`}
              onAdd={() => run({ action: "tag_add", tag_id: tag.id })}
              onRemove={() => run({ action: "tag_remove", tag_id: tag.id })}
            />
          ))}
        </Menu>
        <Menu label="Akte" disabled={busy}>
          {collections.length === 0 && <p className={styles.empty}>Noch keine Akten.</p>}
          {collections.map((collection) => (
            <MenuRow
              key={collection.id}
              name={collection.name}
              addLabel={`Zu Akte „${collection.name}“ hinzufügen`}
              removeLabel={`Aus Akte „${collection.name}“ entfernen`}
              onAdd={() => run({ action: "collection_add", collection_id: collection.id })}
              onRemove={() => run({ action: "collection_remove", collection_id: collection.id })}
            />
          ))}
        </Menu>
        <Menu label="Status setzen" disabled={busy}>
          {REVIEW_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              className={styles.item}
              onClick={() => run({ action: "review", review: key === "unreviewed" ? null : key })}
            >
              {REVIEW_LABELS[key]}
            </button>
          ))}
        </Menu>
        <Menu label="Markierung" disabled={busy}>
          <button
            type="button"
            className={styles.item}
            onClick={() => run({ action: "flag", flagged: true })}
          >
            Markieren
          </button>
          <button
            type="button"
            className={styles.item}
            onClick={() => run({ action: "flag", flagged: false })}
          >
            Markierung entfernen
          </button>
        </Menu>
        <Button size="sm" disabled={busy} onClick={onExport}>
          Exportieren
        </Button>
        <Button size="sm" variant="link" onClick={onClear}>
          Auswahl aufheben
        </Button>
        {busy && <Spinner label="Mails werden geändert" />}
      </div>
      {bulk.isError && (
        <p className={styles.error} role="alert">
          {bulkErrorText(bulk.error)}
        </p>
      )}
    </div>
  );
}

/** "Alle 1.207 Treffer auswählen": every match of the filters instead of this page's. Asks first
 *  above CONFIRM_ABOVE or when the number is not known exactly, and is not offered when more
 *  than BULK_LIMIT match, since the backend refuses those (an inexact number gets its answer). */
function SelectAll({
  selected,
  summary,
  onSelectAll,
}: {
  selected: number;
  summary: MailSummary;
  onSelectAll: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const total = summary.exact ? summary.total : null;

  if (total !== null && total <= selected) return null;
  if (total !== null && total > BULK_LIMIT) {
    return (
      <span className={styles.note}>
        Alle {matches(summary)} sind zu viele für eine Änderung (höchstens{" "}
        {formatNumber(BULK_LIMIT)}).
      </span>
    );
  }
  if (confirming) {
    return (
      <span className={styles.confirm}>
        Wirklich alle {matches(summary)} auswählen?
        <Button
          size="xs"
          variant="primary"
          onClick={() => {
            setConfirming(false);
            onSelectAll();
          }}
        >
          Alle auswählen
        </Button>
        <Button size="xs" onClick={() => setConfirming(false)}>
          Abbrechen
        </Button>
      </span>
    );
  }
  return (
    <Button
      variant="link"
      size="xs"
      onClick={() =>
        total === null || total > CONFIRM_ABOVE ? setConfirming(true) : onSelectAll()
      }
    >
      Alle {matches(summary)} auswählen
    </Button>
  );
}

/** A button that opens a small menu below it; a click outside or Escape closes it, and so does
 *  choosing an entry. */
function Menu({
  label,
  disabled,
  children,
}: {
  label: string;
  disabled: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={root} className={styles.menuRoot}>
      <Button
        size="sm"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        {label} ▾
      </Button>
      {open && (
        <div
          id={menuId}
          role="group"
          aria-label={label}
          className={styles.menu}
          onClick={(event) => {
            if ((event.target as HTMLElement).closest("button")) setOpen(false);
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

/** A tag or Akte in a menu: its name and both changes, each with a label naming it. */
function MenuRow({
  name,
  color,
  addLabel,
  removeLabel,
  onAdd,
  onRemove,
}: {
  name: string;
  color?: string;
  addLabel: string;
  removeLabel: string;
  onAdd: () => void;
  onRemove: () => void;
}) {
  return (
    <div className={styles.row}>
      <span className={styles.name}>
        {color && <span className={styles.dot} style={{ background: color }} aria-hidden="true" />}
        {name}
      </span>
      <Button variant="link" size="xs" aria-label={addLabel} onClick={onAdd}>
        hinzufügen
      </Button>
      <Button variant="link" size="xs" aria-label={removeLabel} onClick={onRemove}>
        entfernen
      </Button>
    </div>
  );
}
