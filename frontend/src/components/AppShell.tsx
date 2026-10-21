import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useStats } from "../api/queries";
import type { ImportState } from "../api/types";
import { cx } from "../lib/cx";
import { useEditor } from "../lib/editor";
import { formatNumber } from "../lib/format";
import { isPlainKey } from "../lib/keys";
import styles from "./AppShell.module.css";
import { EditorDialog } from "./EditorDialog";
import { LogoIcon, SearchIcon } from "./icons";

const NAVIGATION = [
  { to: "/mails", label: "Mails" },
  { to: "/personen", label: "Personen" },
  { to: "/anhaenge", label: "Anhänge" },
  { to: "/entitaeten", label: "Entitäten" },
  { to: "/karte", label: "Karte" },
  { to: "/akten", label: "Akten" },
  { to: "/import", label: "Import" },
];

/** The frame of every screen: header with logo, navigation, global search and figures. */
export function AppShell() {
  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <Link to="/mails" className={styles.logo}>
          <LogoIcon />
          Mailrobbe
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

/** Search over the whole archive: Enter opens the mail list with just this query, "/" focuses
 *  the field, and on the list it shows the list's query. */
function GlobalSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const input = useRef<HTMLInputElement>(null);
  const current = location.pathname.startsWith("/mails")
    ? (new URLSearchParams(location.search).get("q") ?? "")
    : "";

  useEffect(() => {
    if (input.current) input.current.value = current;
  }, [current]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "/" || !isPlainKey(event)) return;
      event.preventDefault();
      input.current?.focus();
      input.current?.select();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = input.current?.value.trim() ?? "";
    void navigate(q ? `/mails?${new URLSearchParams({ q })}` : "/mails");
  }

  return (
    <form role="search" className={styles.search} onSubmit={onSubmit}>
      <SearchIcon className={styles.searchIcon} />
      <label htmlFor="global-search" className="sr-only">
        Suche
      </label>
      <input
        ref={input}
        id="global-search"
        type="search"
        defaultValue={current}
        placeholder="Volltext, Betreff, Adresse, Domain, Message-ID … (from:anna@ to:@beispiel.de has:attachment)"
        autoComplete="off"
        spellCheck={false}
        className={styles.searchInput}
      />
      <kbd className={styles.kbd} aria-hidden="true">
        /
      </kbd>
    </form>
  );
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
    <Link to="/import" className={cx(styles.importState, tone)}>
      <span className={styles.importDot} aria-hidden="true" />
      {text}
    </Link>
  );
}
