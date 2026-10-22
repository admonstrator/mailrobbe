import { useEffect, useId, useRef, useState } from "react";
import { Link, matchPath, NavLink, Outlet, useLocation } from "react-router";

import { useStats } from "../api/queries";
import type { ImportState } from "../api/types";
import { GlobalSearch } from "../features/search/GlobalSearch";
import { cx } from "../lib/cx";
import { useEditor } from "../lib/editor";
import { formatNumber } from "../lib/format";
import styles from "./AppShell.module.css";
import { EditorDialog } from "./EditorDialog";
import { ChevronDownIcon } from "./icons";

interface NavItem {
  to: string;
  label: string;
}

/** The screens of daily work stand in the header, the others in two menus (D312). */
const NAVIGATION: (NavItem | { label: string; items: NavItem[] })[] = [
  { to: "/mails", label: "Mails" },
  { to: "/personen", label: "Personen" },
  { to: "/anhaenge", label: "Anhänge" },
  {
    label: "Auswerten",
    items: [
      { to: "/entitaeten", label: "Entitäten" },
      { to: "/auffaelligkeiten", label: "Signale" },
      { to: "/karte", label: "Karte" },
      { to: "/orte", label: "Orte" },
      { to: "/zeitachse", label: "Zeitachse" },
      { to: "/themen", label: "Themen" },
    ],
  },
  { to: "/akten", label: "Akten" },
  {
    label: "System",
    items: [
      { to: "/ausgeblendet", label: "Ausgeblendet" },
      { to: "/import", label: "Import" },
      { to: "/ki", label: "KI" },
    ],
  },
];

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  cx(styles.navLink, isActive && styles.active);

/** The frame of every screen: header with logo, navigation, global search and figures. */
export function AppShell() {
  const scrolled = useScrolled();
  return (
    <div className={styles.app}>
      <header className={cx(styles.header, scrolled && styles.scrolled)}>
        <Link to="/mails" className={styles.logo}>
          <img src="/logo.svg" alt="" width={28} height={28} />
          <span className={styles.logoText}>Mailrobbe</span>
        </Link>
        <nav aria-label="Hauptnavigation" className={styles.nav}>
          {NAVIGATION.map((entry) =>
            "items" in entry ? (
              <NavMenu key={entry.label} label={entry.label} items={entry.items} />
            ) : (
              <NavLink key={entry.to} to={entry.to} className={navLinkClass}>
                {entry.label}
              </NavLink>
            ),
          )}
        </nav>
        <GlobalSearch />
        <HeaderFigures />
        <EditorName />
      </header>
      <Outlet />
    </div>
  );
}

/** A menu of the navigation: marked active while one of its screens is open. The closed panel
    stays in the page, hidden by its style, so the navigation always holds every screen's link. It
    is placed fixed below its button, so the navigation's sideways scrolling on narrow windows
    does not cut it off. */
function NavMenu({ label, items }: { label: string; items: NavItem[] }) {
  const { pathname } = useLocation();
  const [left, setLeft] = useState<number | null>(null);
  const area = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const open = left !== null;
  const active = items.some(({ to }) => matchPath({ path: to, end: false }, pathname));

  useEffect(() => {
    if (!open) return;
    const close = () => setLeft(null);
    const outside = (event: PointerEvent) => {
      if (!area.current?.contains(event.target as Node)) close();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      close();
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  const toggle = () => {
    const rect = button.current?.getBoundingClientRect();
    setLeft(open || !rect ? null : Math.max(8, Math.min(rect.left, window.innerWidth - 228)));
  };

  return (
    <div ref={area} className={styles.menu}>
      <button
        ref={button}
        type="button"
        className={cx(styles.navLink, styles.menuButton, active && styles.active)}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={toggle}
      >
        {label}
        <ChevronDownIcon size={14} className={styles.chevron} />
      </button>
      <div
        id={panelId}
        className={cx(styles.panel, open && styles.panelOpen)}
        style={left === null ? undefined : { left }}
        onClick={() => setLeft(null)}
      >
        {items.map(({ to, label: text }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => cx(styles.panelLink, isActive && styles.active)}
          >
            {text}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

/** Whether the window is scrolled, which lifts the header off the page with a shadow. */
function useScrolled(): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 0);
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);
  return scrolled;
}

function HeaderFigures() {
  const { data: stats } = useStats();
  if (!stats) return <div className={styles.figures} />;
  return (
    <div className={styles.figures}>
      <span className={styles.count}>
        <strong>{formatNumber(stats.mails)}</strong> Mails
      </span>
      <span className={styles.count}>
        <strong>{formatNumber(stats.persons)}</strong> Personen
      </span>
      <ImportIndicator importer={stats.importer} />
    </div>
  );
}

/** The editor's name (D54), which notes and changes carry; a click changes it. */
function EditorName() {
  const editor = useEditor();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={styles.editor}
        title="Name für Notizen und Änderungen"
        onClick={() => setOpen(true)}
      >
        {editor ? (
          <>
            <span className={styles.editorPrefix}>Bearbeitet als</span> <strong>{editor}</strong>
          </>
        ) : (
          "Namen eintragen"
        )}
      </button>
      {open && <EditorDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function ImportIndicator({ importer }: { importer: ImportState }) {
  if (importer.files_total === 0) return null;
  const percent = `${Math.floor(importer.progress * 100)} %`;
  const [text, tone] = importer.running
    ? [`Import läuft · ${percent}`, styles.running]
    : importer.files_done < importer.files_total
      ? [`Import unterbrochen · ${percent}`, styles.stopped]
      : ["Import fertig", styles.done];
  return (
    <Link to="/import" className={cx(styles.importState, tone)} title={text}>
      <span className={styles.importDot} aria-hidden="true" />
      <span className={styles.importText}>{text}</span>
    </Link>
  );
}
