import { useState, type ReactNode } from "react";

import type { ResearchOverview, ReviewKey } from "../../api/types";
import { Checkbox } from "../../components/Checkbox";
import { formatNumber } from "../../lib/format";
import { REVIEW_KEYS, REVIEW_LABELS, TAG_PALETTE } from "../../lib/research";
import styles from "./FilterColumn.module.css";
import type { FilterPatch, ListState } from "./listState";
import { ReviewMark } from "./ReviewMark";

/** Tags and Akten listed before "Alle anzeigen". */
const TOP_LINKS = 5;

function toggled<T>(values: T[], value: T, checked: boolean): T[] {
  return checked ? [...values, value] : values.filter((other) => other !== value);
}

/** The group "Recherche" of the filter column (D55 to D58): status, bookmark, note, tags and
 *  Akten. Each kind is "any of". The counts are the whole archive's, from the research overview,
 *  and say so, since the other counts next to them could pass for the filter's. */
export function ResearchFilters({
  state,
  change,
  research,
}: {
  state: ListState;
  change: (patch: FilterPatch) => void;
  research: ResearchOverview | undefined;
}) {
  const tags = [...(research?.tags ?? [])].sort(
    (a, b) => b.mails - a.mails || a.name.localeCompare(b.name, "de"),
  );
  const review = (key: ReviewKey, checked: boolean) =>
    change({
      review: REVIEW_KEYS.filter((other) => toggled(state.review, key, checked).includes(other)),
    });

  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Recherche</legend>
      <p className={styles.scope}>Zahlen für das ganze Archiv</p>
      <div className={styles.sub} role="group" aria-label="Status">
        {REVIEW_KEYS.map((key) => (
          <Checkbox
            key={key}
            checked={state.review.includes(key)}
            onChange={(checked) => review(key, checked)}
            count={research?.review[key]}
          >
            <ReviewMark status={key} decorative />
            {REVIEW_LABELS[key]}
          </Checkbox>
        ))}
      </div>
      <div className={styles.sub}>
        <Checkbox
          checked={state.flagged}
          onChange={(flagged) => change({ flagged })}
          count={research?.flagged}
        >
          Nur markierte
        </Checkbox>
        <Checkbox checked={state.has_note} onChange={(has_note) => change({ has_note })}>
          Mit Notiz
        </Checkbox>
      </div>
      <LinkFilter
        title="Schlagwörter"
        items={tags}
        selected={state.tag}
        unknown={(id) => `Schlagwort #${id}`}
        dot={(id) => {
          const tag = tags.find((other) => other.id === id);
          return (
            tag && (
              <span
                className={styles.dot}
                style={{ background: TAG_PALETTE[tag.color].text }}
                aria-hidden="true"
              />
            )
          );
        }}
        onToggle={(id, checked) => change({ tag: toggled(state.tag, id, checked) })}
      />
      <LinkFilter
        title="Akten"
        items={research?.collections ?? []}
        selected={state.collection}
        unknown={(id) => `Akte #${id}`}
        onToggle={(id, checked) => change({ collection: toggled(state.collection, id, checked) })}
      />
    </fieldset>
  );
}

/** Checkboxes for tags or Akten: the first few, those selected, and the rest on request. Ids
 *  from the URL that no longer exist show by number, so they can be unchecked. */
function LinkFilter({
  title,
  items,
  selected,
  unknown,
  dot,
  onToggle,
}: {
  title: string;
  items: { id: number; name: string; mails: number }[];
  selected: number[];
  unknown: (id: number) => string;
  dot?: (id: number) => ReactNode;
  onToggle: (id: number, checked: boolean) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, TOP_LINKS);
  const others = selected.filter((id) => !shown.some((item) => item.id === id));
  if (items.length === 0 && selected.length === 0) return null;
  return (
    <div className={styles.sub} role="group" aria-label={title}>
      <span className={styles.subLegend}>{title}</span>
      {shown.map((item) => (
        <Checkbox
          key={item.id}
          checked={selected.includes(item.id)}
          onChange={(checked) => onToggle(item.id, checked)}
          count={item.mails}
        >
          {dot?.(item.id)}
          {item.name}
        </Checkbox>
      ))}
      {others.map((id) => (
        <Checkbox key={id} checked onChange={(checked) => onToggle(id, checked)}>
          {dot?.(id)}
          {items.find((item) => item.id === id)?.name ?? unknown(id)}
        </Checkbox>
      ))}
      {items.length > TOP_LINKS && (
        <button type="button" className={styles.more} onClick={() => setAll(!all)}>
          {all ? "Weniger anzeigen" : `Alle ${formatNumber(items.length)} anzeigen`}
        </button>
      )}
    </div>
  );
}
