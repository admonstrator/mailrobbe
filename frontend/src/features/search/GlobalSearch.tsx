import { useEffect, useId, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router";

import { useStats } from "../../api/queries";
import { HelpIcon, SearchIcon, SlidersIcon } from "../../components/icons";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { isPlainKey } from "../../lib/keys";
import { RuleDialog } from "../hiding/RuleDialog";
import { filterChips } from "../mails/chips";
import {
  DEFAULT_LIST_STATE,
  hasFilters,
  listSearch,
  parseListState,
  searchOptions,
  withFilters,
  type FilterPatch,
  type SearchOptions as Options,
} from "../mails/listState";
import { SaveSearchDialog } from "../mails/SaveSearchDialog";
import { changedOptions, DEFAULT_SEARCH_OPTIONS } from "../mails/SearchOptions";
import styles from "./GlobalSearch.module.css";
import { OPERATORS_HEADING, SearchMenu } from "./SearchMenu";

/** The widest the menu gets, and its distance to the window's edges. */
const MENU_WIDTH = 680;
const MENU_MARGIN = 16;

/** q with the words of text appended as excluded terms ("-Wort"; a quoted phrase stays one). */
export function withExcluded(q: string, text: string): string {
  const terms = (text.match(/"[^"]*"?|\S+/g) ?? []).map((term) =>
    term.startsWith("-") ? term : `-${term}`,
  );
  return [q.trim(), ...terms.filter((term) => term !== "-")].filter(Boolean).join(" ");
}

/** Search over the whole archive with its menu: Enter opens the mail list with this query, "/"
 *  focuses the field, and on the list it shows the list's query. On the list (and a mail opened
 *  from it) the menu's options act on the list at once and a new search keeps them (D177); on
 *  the other screens the menu keeps them until the next search. */
export function GlobalSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: stats } = useStats();
  const input = useRef<HTMLInputElement>(null);
  const area = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const help = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const menuId = useId();
  // The menu opened by its button, or by the help button at its operators (D340).
  const [open, setOpen] = useState<false | "menu" | "operators">(false);
  const opener = useRef<"menu" | "operators">("menu");
  const [saving, setSaving] = useState(false);
  const [creatingRule, setCreatingRule] = useState(false);
  const [draft, setDraft] = useState<Options>(DEFAULT_SEARCH_OPTIONS);

  const onList = location.pathname.startsWith("/mails");
  const list = onList ? parseListState(new URLSearchParams(location.search)) : null;
  const current = list?.q ?? "";
  const options = list ? searchOptions(list) : draft;
  const changed = changedOptions(options);

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

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) (opener.current === "operators" ? help : toggle).current?.focus();
  }

  function openAt(at: "menu" | "operators") {
    opener.current = at;
    setOpen(at);
  }

  // Escape, a click outside and focus leaving the search close the menu.
  useEffect(() => {
    if (!open) return;
    const inside = (target: EventTarget | null) =>
      target instanceof Node && !!area.current?.contains(target);
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close(true);
    }
    function onPointerDown(event: PointerEvent) {
      if (!inside(event.target)) close(false);
    }
    function onFocusIn(event: FocusEvent) {
      if (!inside(event.target)) close(false);
    }
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("focusin", onFocusIn);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("focusin", onFocusIn);
    };
  }, [open]);

  // Below the field, as wide as the window allows, moved left where the window ends.
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      if (!area.current || !panel.current) return;
      const left = area.current.getBoundingClientRect().left;
      const room = document.documentElement.clientWidth; // without the window's scrollbar
      const width = Math.min(MENU_WIDTH, room - 2 * MENU_MARGIN);
      const shift = Math.min(0, room - MENU_MARGIN - (left + width));
      panel.current.style.width = `${width}px`;
      panel.current.style.left = `${Math.max(shift, MENU_MARGIN - left)}px`;
    }
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const target =
      open === "operators"
        ? `#${OPERATORS_HEADING}`
        : "input:not(:disabled), button:not(:disabled), a[href]";
    panel.current?.querySelector<HTMLElement>(target)?.focus();
  }, [open]);

  /** On the list the options and exclusions change its URL; a new filter starts at page 1. */
  function changeList(patch: FilterPatch) {
    if (!list) return;
    const search = listSearch(withFilters(list, patch)).toString();
    void navigate(search ? `${location.pathname}?${search}` : location.pathname, {
      preventScrollReset: true,
    });
  }

  function change(patch: Partial<Options>) {
    if (list) changeList(patch);
    else setDraft((before) => ({ ...before, ...patch }));
  }

  function exclude(text: string) {
    const field = input.current;
    if (!field) return;
    field.value = withExcluded(field.value, text);
    if (list) changeList({ q: field.value });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = input.current?.value.trim() ?? "";
    const search = listSearch({ ...DEFAULT_LIST_STATE, ...options, q }).toString();
    setOpen(false);
    void navigate(search ? `/mails?${search}` : "/mails");
  }

  const saveable = list && hasFilters(list) ? list : null;

  return (
    <div ref={area} className={styles.area}>
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
          placeholder={
            stats ? `In ${formatNumber(stats.mails)} Mails suchen` : "In den Mails suchen"
          }
          title="Wörter, Phrasen und Operatoren wie to:@beispiel.de, recipient:.ru oder between:anna,bert"
          autoComplete="off"
          spellCheck={false}
          className={styles.searchInput}
        />
        <kbd className={styles.kbd} aria-hidden="true">
          /
        </kbd>
        <button
          ref={help}
          type="button"
          className={cx(styles.menuButton, open === "operators" && styles.menuButtonOn)}
          aria-label="Operatoren der Suche"
          title="Operatoren der Suche: from:, to:, recipient:, between:, domain: …"
          aria-haspopup="dialog"
          aria-expanded={open === "operators"}
          aria-controls={menuId}
          onClick={() => (open === "operators" ? close(true) : openAt("operators"))}
        >
          <HelpIcon />
        </button>
        <button
          ref={toggle}
          type="button"
          className={cx(styles.menuButton, (open === "menu" || changed > 0) && styles.menuButtonOn)}
          aria-label={changed > 0 ? `Suchmenü, ${changed} Optionen geändert` : "Suchmenü"}
          title="Suchoptionen, Ausschließen, Operatoren und gespeicherte Suchen"
          aria-haspopup="dialog"
          aria-expanded={open === "menu"}
          aria-controls={menuId}
          onClick={() => (open === "menu" ? close(true) : openAt("menu"))}
        >
          <SlidersIcon />
          {changed > 0 && (
            <span className={styles.badge} aria-hidden="true">
              {changed}
            </span>
          )}
        </button>
      </form>
      <div
        ref={panel}
        id={menuId}
        role="dialog"
        aria-label="Suchmenü"
        className={styles.panel}
        hidden={!open}
      >
        {open && (
          <SearchMenu
            options={options}
            onList={list !== null}
            change={change}
            exclude={exclude}
            save={
              saveable &&
              (() => {
                setOpen(false);
                setSaving(true);
              })
            }
            onLeave={() => setOpen(false)}
            newRule={() => {
              setOpen(false);
              setCreatingRule(true);
            }}
          />
        )}
      </div>
      {saving && saveable && (
        <SaveSearchDialog
          query={listSearch({ ...saveable, cursor: null, page: 1 }).toString()}
          suggestedName={
            saveable.q ||
            filterChips(saveable, [], {
              person: (id) => `Person #${id}`,
              mboxFile: (id) => `Datei #${id}`,
              tag: () => undefined,
              collection: () => undefined,
            })
              .map((chip) => chip.label)
              .join(" · ")
          }
          onClose={() => setSaving(false)}
        />
      )}
      {creatingRule && <RuleDialog draft={{}} onClose={() => setCreatingRule(false)} />}
    </div>
  );
}
