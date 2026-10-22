import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";

import { useStats } from "../api/queries";
import type { ImportState } from "../api/types";
import { GlobalSearch } from "../features/search/GlobalSearch";
import { cx } from "../lib/cx";
import { useEditor } from "../lib/editor";
import { formatNumber } from "../lib/format";
import styles from "./AppShell.module.css";
import { EditorDialog } from "./EditorDialog";

const NAVIGATION = [
  { to: "/mails", label: "Mails" },
  { to: "/personen", label: "Personen" },
  { to: "/anhaenge", label: "Anhänge" },
  { to: "/entitaeten", label: "Entitäten" },
  { to: "/auffaelligkeiten", label: "Signale" },
  { to: "/karte", label: "Karte" },
  { to: "/orte", label: "Orte" },
  { to: "/zeitachse", label: "Zeitachse" },
  { to: "/themen", label: "Themen" },
  { to: "/akten", label: "Akten" },
  { to: "/ausgeblendet", label: "Ausgeblendet" },
  { to: "/import", label: "Import" },
  { to: "/ki", label: "KI" },
];

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
          {NAVIGATION.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => cx(styles.navLink, isActive && styles.active)}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <GlobalSearch />
        <HeaderFigures />
        <EditorName />
      </header>
      <Outlet />
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
