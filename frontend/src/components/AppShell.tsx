import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router";

import { useStats } from "../api/queries";
import type { ImportState } from "../api/types";
import { GlobalSearch } from "../features/search/GlobalSearch";
import { cx } from "../lib/cx";
import { useEditor } from "../lib/editor";
import styles from "./AppShell.module.css";
import { EditorDialog } from "./EditorDialog";
import { HistoryMenu } from "./HistoryMenu";
import { ThemeButton } from "./ThemeButton";
import { MenuIcon } from "./icons";
import { setSidebarFolded, Sidebar, useSidebarFolded } from "./Sidebar";

/** The frame of every screen (D332): the header on the ground colour with the sidebar's button,
 *  the logo, the global search, the history (D333), the import state and the editor; the sidebar
 *  at the left; and the white sheet every page sits on. Pages keep their own `main`. */
export function AppShell() {
  const scrolled = useScrolled();
  const folded = useSidebarFolded();
  return (
    <div className={styles.app}>
      <header className={cx(styles.header, scrolled && styles.scrolled)}>
        <button
          type="button"
          className={styles.iconButton}
          aria-label={folded ? "Seitenleiste ausklappen" : "Seitenleiste einklappen"}
          title={folded ? "Seitenleiste ausklappen" : "Seitenleiste einklappen"}
          aria-expanded={!folded}
          onClick={() => setSidebarFolded(!folded)}
        >
          <MenuIcon size={20} strokeWidth={1.8} />
        </button>
        <Link to="/mails" className={styles.logo}>
          <img src="/logo.svg" alt="" width={28} height={28} />
          <span className={styles.logoText}>Mailrobbe</span>
        </Link>
        <GlobalSearch />
        <div className={styles.end}>
          <ThemeButton />
          <HistoryMenu />
          <ImportIndicator />
          <EditorName />
        </div>
      </header>
      <div className={styles.body}>
        <Sidebar />
        <div className={styles.sheet}>
          <Outlet />
        </div>
      </div>
    </div>
  );
}

/** Whether the window is scrolled, which lifts the header off the page with a line. */
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

/** Up to two letters of a name: "Lena Vogt" -> "LV", "lena" -> "LE". */
export function nameInitials(name: string): string {
  const words = name.split(/\s+/).filter((word) => /\p{L}/u.test(word));
  const letter = (word: string) => word.match(/\p{L}/u)?.[0] ?? "";
  const text =
    words.length >= 2
      ? letter(words[0]) + letter(words[words.length - 1])
      : [...(words[0] ?? name).replace(/[^\p{L}\p{N}]/gu, "")].slice(0, 2).join("");
  return text.toUpperCase() || "?";
}

const EDITOR_COLOURS = ["#0f766e", "#1d5bd6", "#7c3aed", "#be185d", "#b45309", "#15803d"];

function editorColour(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + char.codePointAt(0)!) >>> 0;
  return EDITOR_COLOURS[hash % EDITOR_COLOURS.length];
}

/** The editor's name (D54) as a round avatar, which notes and changes carry; a click changes
 *  it. Without a name a button asks for one. */
function EditorName() {
  const editor = useEditor();
  const [open, setOpen] = useState(false);
  return (
    <>
      {editor ? (
        <button
          type="button"
          className={styles.avatar}
          style={{ background: editorColour(editor) }}
          aria-label={`Bearbeitet als ${editor}`}
          title={`Bearbeitet als ${editor}`}
          onClick={() => setOpen(true)}
        >
          <span aria-hidden="true">{nameInitials(editor)}</span>
        </button>
      ) : (
        <button
          type="button"
          className={styles.editor}
          title="Name für Notizen und Änderungen"
          onClick={() => setOpen(true)}
        >
          Namen eintragen
        </button>
      )}
      {open && <EditorDialog onClose={() => setOpen(false)} />}
    </>
  );
}

/** The import's state, linking to the dashboard: a small bar and the percentage while it runs. */
function ImportIndicator() {
  const { data: stats } = useStats();
  if (!stats) return null;
  return <ImportState importer={stats.importer} />;
}

function ImportState({ importer }: { importer: ImportState }) {
  if (importer.files_total === 0) return null;
  const percent = Math.floor(importer.progress * 100);
  if (importer.running) {
    return (
      <Link
        to="/import"
        className={cx(styles.importState, styles.running)}
        title={`Import läuft · ${percent} %`}
      >
        <span className={styles.importTrack} aria-hidden="true">
          <span className={styles.importFill} style={{ width: `${percent}%` }} />
        </span>
        <span className={styles.importText}>{`Import ${percent} %`}</span>
      </Link>
    );
  }
  const [text, tone] =
    importer.files_done < importer.files_total
      ? [`Import unterbrochen · ${percent} %`, styles.stopped]
      : ["Import fertig", styles.done];
  return (
    <Link to="/import" className={cx(styles.importState, tone)} title={text}>
      <span className={styles.importDot} aria-hidden="true" />
      <span className={styles.importText}>{text}</span>
    </Link>
  );
}
