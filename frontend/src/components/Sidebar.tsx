import { useSyncExternalStore, type ComponentType } from "react";
import { Link, NavLink, useLocation } from "react-router";

import { useResearch, useStats } from "../api/queries";
import { cx } from "../lib/cx";
import { formatNumber } from "../lib/format";
import { useHistory } from "../lib/history";
import {
  ChevronsLeftIcon,
  EyeOffIcon,
  FlagIcon,
  FolderIcon,
  GearIcon,
  GraphIcon,
  HashIcon,
  ImportIcon,
  MailIcon,
  PaperclipIcon,
  PersonsIcon,
  PinIcon,
  PulseIcon,
  SparkIcon,
  TagIcon,
} from "./icons";
import styles from "./Sidebar.module.css";

// Folding (D332): the reader's choice is kept in this browser; without one the sidebar starts
// folded below 1280 px of window width and follows the window until a choice is made.

const STORAGE_KEY = "mailrobbe.sidebar";
const NARROW = "(max-width: 1279px)";

const listeners = new Set<() => void>();
let fallback: string | null = null; // when the browser keeps no storage

function storedChoice(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return fallback;
  }
}

function narrowWindow(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW).matches;
}

function folded(): boolean {
  const choice = storedChoice();
  if (choice === "folded") return true;
  if (choice === "open") return false;
  return narrowWindow();
}

export function setSidebarFolded(value: boolean): void {
  const choice = value ? "folded" : "open";
  fallback = choice;
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // kept in memory for this page only
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  const media = typeof window.matchMedia === "function" ? window.matchMedia(NARROW) : null;
  media?.addEventListener("change", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
    media?.removeEventListener("change", listener);
  };
}

/** Whether the sidebar shows icons only. */
export function useSidebarFolded(): boolean {
  return useSyncExternalStore(subscribe, folded, () => false);
}

type IconComponent = ComponentType<{ size?: number; className?: string; strokeWidth?: number }>;

interface Item {
  to: string;
  label: string;
  icon: IconComponent;
  /** The tooltip when it says more than the label. */
  title?: string;
  count?: number;
}

/** Saved searches the sidebar lists; "Alle" leads to the rest. */
const SAVED_SHOWN = 6;

/** Colours of the saved searches' marks, by id. */
const SEARCH_COLOURS = ["#1d5bd6", "#d97706", "#7c3aed", "#0f766e", "#be185d", "#15803d"];

function NavItem({ item, folded: iconsOnly }: { item: Item; folded: boolean }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      title={item.title ?? item.label}
      className={({ isActive }) => cx(styles.item, isActive && styles.active)}
    >
      <Icon size={18} strokeWidth={1.8} className={styles.icon} />
      <span className={cx(styles.label, iconsOnly && "sr-only")}>{item.label}</span>
      {item.count !== undefined && !iconsOnly && (
        <span className={styles.count} aria-hidden="true">
          {formatNumber(item.count)}
        </span>
      )}
    </NavLink>
  );
}

/** The caption of a group of links. Not a heading: the sidebar stands before every page's own
 *  title and should not add to the page's outline. */
function Group({ title, folded: iconsOnly }: { title: string; folded: boolean }) {
  return iconsOnly ? (
    <div className={styles.rule} role="separator" aria-label={title} />
  ) : (
    <p className={styles.heading}>{title}</p>
  );
}

/** The navigation at the left of every screen (D332): the screens of daily work with their
 *  counts, the evaluations, the team's saved searches, the system pages and the newest entries
 *  of the history (D333). It folds to a column of icons. */
export function Sidebar() {
  const iconsOnly = useSidebarFolded();
  const { data: stats } = useStats();
  const research = useResearch();
  const history = useHistory();
  const location = useLocation();
  const searches = research.data?.searches ?? [];

  const daily: Item[] = [
    { to: "/mails", label: "Mails", icon: MailIcon, count: stats?.mails },
    { to: "/personen", label: "Personen", icon: PersonsIcon, count: stats?.persons },
    { to: "/anhaenge", label: "Anhänge", icon: PaperclipIcon },
    {
      to: "/akten",
      label: "Akten",
      icon: FolderIcon,
      count: research.data?.collections.length,
    },
  ];
  const evaluate: Item[] = [
    { to: "/zeitachse", label: "Zeitachse", icon: PulseIcon },
    { to: "/karte", label: "Karte", icon: GraphIcon, title: "Beziehungskarte" },
    { to: "/orte", label: "Orte", icon: PinIcon },
    { to: "/auffaelligkeiten", label: "Signale", icon: FlagIcon },
    { to: "/entitaeten", label: "Entitäten", icon: TagIcon },
    { to: "/themen", label: "Themen", icon: HashIcon },
  ];
  const system: Item[] = [
    { to: "/import", label: "Import", icon: ImportIcon },
    { to: "/ki", label: "KI", icon: SparkIcon },
    { to: "/ausgeblendet", label: "Ausgeblendet", icon: EyeOffIcon },
    { to: "/einstellungen", label: "Einstellungen", icon: GearIcon },
  ];
  const currentSearch = location.pathname === "/mails" ? location.search.replace(/^\?/, "") : null;

  return (
    <aside className={cx(styles.sidebar, iconsOnly && styles.folded)} aria-label="Seitenleiste">
      <nav aria-label="Hauptnavigation" className={styles.nav}>
        {daily.map((item) => (
          <NavItem key={item.to} item={item} folded={iconsOnly} />
        ))}
        <Group title="Auswerten" folded={iconsOnly} />
        {evaluate.map((item) => (
          <NavItem key={item.to} item={item} folded={iconsOnly} />
        ))}
        {searches.length > 0 && (
          <>
            <Group title="Gespeicherte Suchen" folded={iconsOnly} />
            {searches.slice(0, SAVED_SHOWN).map((search) => (
              <Link
                key={search.id}
                to={search.query ? `/mails?${search.query}` : "/mails"}
                title={search.name}
                aria-label={`Gespeicherte Suche: ${search.name}`}
                className={cx(styles.item, currentSearch === search.query && styles.active)}
                aria-current={currentSearch === search.query ? "page" : undefined}
              >
                <span
                  className={styles.mark}
                  style={{ background: SEARCH_COLOURS[search.id % SEARCH_COLOURS.length] }}
                  aria-hidden="true"
                />
                <span className={cx(styles.label, iconsOnly && "sr-only")}>{search.name}</span>
              </Link>
            ))}
            {searches.length > SAVED_SHOWN && !iconsOnly && (
              <Link to="/akten?tab=suchen" className={cx(styles.item, styles.more)}>
                {`Alle ${formatNumber(searches.length)}`}
              </Link>
            )}
          </>
        )}
        <Group title="System" folded={iconsOnly} />
        {system.map((item) => (
          <NavItem key={item.to} item={item} folded={iconsOnly} />
        ))}
      </nav>
      {!iconsOnly && history.length > 0 && (
        <section aria-labelledby="sidebar-recent" className={styles.recent}>
          <p id="sidebar-recent" className={styles.heading}>
            Zuletzt angesehen
          </p>
          {history.slice(0, 3).map((visit) => (
            <Link
              key={`${visit.kind}:${visit.id}`}
              to={visit.path}
              title={visit.subtitle ? `${visit.title} · ${visit.subtitle}` : visit.title}
              className={styles.recentLink}
            >
              {visit.title || "(ohne Titel)"}
            </Link>
          ))}
        </section>
      )}
      <button
        type="button"
        className={styles.fold}
        title={iconsOnly ? "Seitenleiste ausklappen" : "Seitenleiste einklappen"}
        onClick={() => setSidebarFolded(!iconsOnly)}
      >
        <ChevronsLeftIcon size={18} strokeWidth={1.8} className={styles.foldIcon} />
        <span className={cx(iconsOnly && "sr-only")}>
          {iconsOnly ? "Ausklappen" : "Einklappen"}
        </span>
      </button>
    </aside>
  );
}
