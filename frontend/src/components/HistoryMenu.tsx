import { useEffect, useId, useRef, useState, type ComponentType } from "react";
import { Link } from "react-router";

import { cx } from "../lib/cx";
import {
  clearHistory,
  HISTORY_LIMIT,
  removeVisit,
  useHistory,
  type Visit,
  type VisitKind,
} from "../lib/history";
import styles from "./HistoryMenu.module.css";
import { CrossIcon, FileIcon, FolderIcon, HistoryIcon, MailIcon, PersonIcon } from "./icons";

type Filter = "all" | VisitKind;

const FILTERS: [Filter, string][] = [
  ["all", "Alle"],
  ["mail", "Mails"],
  ["person", "Personen"],
  ["document", "Dokumente"],
  ["akte", "Akten"],
];

const KIND_ICONS: Record<VisitKind, ComponentType<{ size?: number }>> = {
  mail: MailIcon,
  person: PersonIcon,
  document: FileIcon,
  akte: FolderIcon,
};

const KIND_LABELS: Record<VisitKind, string> = {
  mail: "Mail",
  person: "Person",
  document: "Dokument",
  akte: "Akte",
};

type Group = "Heute" | "Gestern" | "Älter";

const startOfDay = (date: Date) =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();

/** The group of a visit by the reader's calendar days. */
export function visitGroup(at: number, now: Date = new Date()): Group {
  const today = startOfDay(now);
  if (at >= today) return "Heute";
  const yesterday = startOfDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  return at >= yesterday ? "Gestern" : "Älter";
}

const clock = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
const WEEKDAYS = ["So.", "Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa."];
const twoDigits = (value: number) => String(value).padStart(2, "0");

/** "vor 4 Min." within the last hour, "17:42" today and yesterday, "Mo., 20.10." before. */
export function visitTime(at: number, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - at) / 60_000);
  const group = visitGroup(at, now);
  if (group === "Heute" && minutes < 1) return "gerade eben";
  if (group === "Heute" && minutes < 60) return `vor ${minutes} Min.`;
  const date = new Date(at);
  if (group !== "Älter") return clock.format(date);
  return `${WEEKDAYS[date.getDay()]}, ${twoDigits(date.getDate())}.${twoDigits(date.getMonth() + 1)}.`;
}

/** The history's button in the header and its popover (D333): what was opened in this browser,
 *  by kind and day, each entry removable, the whole list clearable. */
export function HistoryMenu() {
  const [open, setOpen] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!area.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={area} className={styles.area}>
      <button
        ref={button}
        type="button"
        className={cx(styles.button, open && styles.buttonOn)}
        aria-label="Zuletzt angesehen"
        title="Zuletzt angesehen"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen(!open)}
      >
        <HistoryIcon size={20} strokeWidth={1.8} />
      </button>
      {open && <HistoryPanel id={panelId} onLeave={() => setOpen(false)} />}
    </div>
  );
}

function HistoryPanel({ id, onLeave }: { id: string; onLeave: () => void }) {
  const history = useHistory();
  const [filter, setFilter] = useState<Filter>("all");
  const panel = useRef<HTMLDivElement>(null);
  const now = new Date();
  const shown = history.filter((visit) => filter === "all" || visit.kind === filter);
  const groups = (["Heute", "Gestern", "Älter"] as const)
    .map((title) => ({ title, visits: shown.filter((v) => visitGroup(v.at, now) === title) }))
    .filter((group) => group.visits.length > 0);

  useEffect(() => {
    panel.current?.focus();
  }, []);

  return (
    <div
      ref={panel}
      id={id}
      role="dialog"
      aria-label="Zuletzt angesehen"
      tabIndex={-1}
      className={styles.panel}
    >
      <div className={styles.head}>
        <h2 className={styles.title}>Zuletzt angesehen</h2>
        {history.length > 0 && (
          <button type="button" className={styles.clear} onClick={clearHistory}>
            Verlauf leeren
          </button>
        )}
      </div>
      <div role="group" aria-label="Art" className={styles.filters}>
        {FILTERS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={filter === key}
            className={cx(styles.filter, filter === key && styles.filterOn)}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {groups.length === 0 ? (
        <p className={styles.empty}>
          {history.length === 0
            ? "Noch nichts angesehen. Geöffnete Mails, Personen, Dokumente und Akten erscheinen hier."
            : "Nichts dieser Art angesehen."}
        </p>
      ) : (
        groups.map((group) => (
          <section key={group.title} aria-label={group.title}>
            <h3 className={styles.group}>{group.title}</h3>
            <ul className={styles.list}>
              {group.visits.map((visit) => (
                <Entry
                  key={`${visit.kind}:${visit.id}`}
                  visit={visit}
                  now={now}
                  onLeave={onLeave}
                />
              ))}
            </ul>
          </section>
        ))
      )}
      <p className={styles.foot}>
        {`Nur in diesem Browser gespeichert, höchstens ${HISTORY_LIMIT} Einträge.`}
      </p>
    </div>
  );
}

function Entry({ visit, now, onLeave }: { visit: Visit; now: Date; onLeave: () => void }) {
  const Icon = KIND_ICONS[visit.kind];
  return (
    <li className={styles.entry}>
      <span className={cx(styles.kind, styles[visit.kind])} title={KIND_LABELS[visit.kind]}>
        <Icon size={16} />
      </span>
      <Link to={visit.path} className={styles.link} onClick={onLeave}>
        <span className={styles.entryTitle}>{visit.title || "(ohne Titel)"}</span>
        {visit.subtitle && <span className={styles.subtitle}>{visit.subtitle}</span>}
      </Link>
      <time className={styles.time} dateTime={new Date(visit.at).toISOString()}>
        {visitTime(visit.at, now)}
      </time>
      <button
        type="button"
        className={styles.remove}
        aria-label={`Aus dem Verlauf entfernen: ${visit.title}`}
        title="Aus dem Verlauf entfernen"
        onClick={() => removeVisit(visit.kind, visit.id)}
      >
        <CrossIcon size={14} />
      </button>
    </li>
  );
}
