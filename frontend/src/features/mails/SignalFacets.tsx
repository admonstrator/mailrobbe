import { useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router";

import { useMailSummary, useSignalFacets, useSignals, useThemes } from "../../api/queries";
import type { SignalKey, ThemeInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { mailsText } from "../entities/labels";
import { signalAnchor, signalName, signalThemeInfo } from "../signals/labels";
import type { ChipNames } from "./chips";
import { columnWide, facetScope, subscribeWidth, useClipped } from "./EntityFacets";
import facets from "./EntityFacets.module.css";
import { toFilters, withFilters, type ListState } from "./listState";
import styles from "./SignalFacets.module.css";

const STORAGE_KEY = "mailrobbe.signal-facets";

function loadOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "closed";
  } catch {
    return true; // storage blocked: open
  }
}

function saveOpen(open: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, open ? "open" : "closed");
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** How many of the list's mails carry each signal (D136), beside the table or above it like the
 *  entity facets, and counted as they are. Mounted at both places; each renders only at its
 *  widths. A click adds the signal to the filter, a second one takes it out again. */
export function SignalFacets({
  state,
  onChange,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  placement: "column" | "top";
}) {
  const wide = useSyncExternalStore(subscribeWidth, columnWide, () => false);
  if (wide !== (placement === "column")) return null;
  return <SignalPanel state={state} onChange={onChange} placement={placement} />;
}

function SignalPanel({
  state,
  onChange,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  placement: "column" | "top";
}) {
  const [open, setOpen] = useState(loadOpen);
  const [expanded, setExpanded] = useState(false);
  const shown = placement === "column" || open;
  const filters = toFilters(state);
  const counts = useSignalFacets(filters, shown);
  const summary = useMailSummary(filters);
  const themes = useThemes();
  const chips = useRef<HTMLUListElement>(null);
  // The response's order is the display order of the signals.
  const entries = Object.entries(counts.data?.signals ?? {}) as [SignalKey, number][];
  const clip = placement === "top" && !expanded;
  const clipped = useClipped(
    chips,
    shown && clip,
    entries.map(([key, mails]) => `${key}:${mails}`).join(),
  );
  const total = summary.data?.exact ? summary.data.total : null;
  const titleId = `signal-facets-title-${placement}`;
  const toggle = (key: SignalKey) =>
    onChange(
      withFilters(state, {
        signal: state.signal.includes(key)
          ? state.signal.filter((other) => other !== key)
          : [...state.signal, key],
      }),
    );
  // No hits: the list says so, and there is nothing to count.
  if (counts.data?.mails === 0 && !counts.isPlaceholderData) return null;

  return (
    <section
      className={cx(facets.panel, facets[placement], !shown && facets.closed)}
      aria-labelledby={titleId}
    >
      <div className={facets.head}>
        <h2 id={titleId} className={facets.title}>
          Signale
        </h2>
        {shown && counts.data && (
          <span className={facets.scope}>{facetScope(counts.data, total)}</span>
        )}
        <span className={facets.headLinks}>
          <Link to="/auffaelligkeiten" className={facets.all}>
            Was Signale sind
          </Link>
          {placement === "top" && (
            <Button
              variant="link"
              size="xs"
              aria-expanded={open}
              onClick={() => {
                setOpen(!open);
                saveOpen(!open);
              }}
            >
              {open ? "Ausblenden" : "Einblenden"}
            </Button>
          )}
        </span>
      </div>
      {shown &&
        (counts.isPending ? (
          <div className={facets.state}>
            <Spinner label="Signale werden geladen" />
          </div>
        ) : counts.isError ? (
          <div className={facets.state} role="alert">
            <span>Die Signale konnten nicht geladen werden.</span>
            <Button size="xs" onClick={() => void counts.refetch()}>
              Erneut versuchen
            </Button>
          </div>
        ) : entries.length === 0 ? (
          <NoSignals filtered={counts.data.mails !== null} />
        ) : (
          <div
            className={cx(
              styles.row,
              placement === "top" && styles.line,
              counts.isPlaceholderData && facets.stale,
            )}
            role="group"
            aria-labelledby={titleId}
          >
            <ul ref={chips} className={cx(facets.chips, clip && facets.clipped)}>
              {entries.map(([key, mails]) => (
                <SignalChip
                  key={key}
                  signal={key}
                  mails={mails}
                  theme={signalThemeInfo(key, themes.data)}
                  selected={state.signal.includes(key)}
                  onToggle={toggle}
                />
              ))}
            </ul>
            {placement === "top" && (clipped || expanded) && (
              <button
                type="button"
                className={facets.more}
                aria-expanded={expanded}
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? "weniger" : "mehr"}
              </button>
            )}
          </div>
        ))}
    </section>
  );
}

/** Nothing counted: no signal holds for these mails, or no signals phase ran yet. */
function NoSignals({ filtered }: { filtered: boolean }) {
  const overview = useSignals();
  const never = overview.data?.computed_at === null;
  return (
    <div className={facets.empty}>
      <p className={facets.emptyTitle}>
        {filtered ? "Keine Signale in diesen Mails" : "Keine Signale"}
      </p>
      {never && <p className={facets.hint}>Signale werden beim nächsten Import berechnet.</p>}
    </div>
  );
}

function SignalChip({
  signal,
  mails,
  theme,
  selected,
  onToggle,
}: {
  signal: SignalKey;
  mails: number;
  theme: ThemeInfo | undefined;
  selected: boolean;
  onToggle: (key: SignalKey) => void;
}) {
  const name = signalName(signal, theme?.name);
  return (
    <li className={cx(facets.chip, selected && facets.selected)}>
      <button
        type="button"
        className={facets.toggle}
        aria-pressed={selected}
        title={
          selected
            ? `${name} · im Filter; Klick nimmt es heraus`
            : `${name} · ${mailsText(mails)}; Klick grenzt die Liste ein`
        }
        onClick={() => onToggle(signal)}
      >
        {theme && (
          <span
            className={facets.dot}
            style={{ background: TAG_PALETTE[theme.color].text }}
            aria-hidden="true"
          />
        )}
        <span className={facets.label}>{name}</span>{" "}
        <span className={facets.count}>{formatNumber(mails)}</span>
      </button>
      <Link
        to={`/auffaelligkeiten#${signalAnchor(signal)}`}
        className={facets.open}
        aria-label={`Regel von ${name}`}
        title={`Regel und Zahlen von ${name}`}
      >
        ›
      </Link>
    </li>
  );
}

/** Names for the chips of the signal filter: a word field by its theme's name and colour. */
export function useSignalChipNames(): NonNullable<ChipNames["signal"]> {
  const themes = useThemes();
  return (key) => {
    const theme = signalThemeInfo(key, themes.data);
    return { name: signalName(key, theme?.name), color: theme?.color };
  };
}
