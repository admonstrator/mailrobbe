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
import { facetScope } from "./EntityFacets";
import facets from "./EntityFacets.module.css";
import { toFilters, withFilters, type ListState } from "./listState";
import styles from "./SignalFacets.module.css";

/** How many of the list's mails carry each signal (D136), in the panel "Einblicke" beside the
 *  list (D335), counted as they are. A click adds the signal to the filter, a second one takes
 *  it out again. */
export function SignalFacets({
  state,
  onChange,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
}) {
  const filters = toFilters(state);
  const counts = useSignalFacets(filters);
  const summary = useMailSummary(filters);
  const themes = useThemes();
  // The response's order is the display order of the signals.
  const entries = Object.entries(counts.data?.signals ?? {}) as [SignalKey, number][];
  const total = summary.data?.exact ? summary.data.total : null;
  const titleId = "signal-facets-title";
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
    <section className={facets.panel} aria-labelledby={titleId}>
      <div className={facets.head}>
        <h3 id={titleId} className={facets.title}>
          Signale
        </h3>
        <span className={facets.headLinks}>
          <Link to="/auffaelligkeiten" className={facets.all}>
            Was Signale sind
          </Link>
        </span>
        {counts.data && <span className={facets.scope}>{facetScope(counts.data, total)}</span>}
      </div>
      {counts.isPending ? (
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
          className={cx(styles.row, counts.isPlaceholderData && facets.stale)}
          role="group"
          aria-labelledby={titleId}
        >
          <ul className={facets.chips}>
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
        </div>
      )}
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
