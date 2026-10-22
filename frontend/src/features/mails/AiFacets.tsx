import { useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react";

import { ApiError } from "../../api/client";
import {
  useAdoptAiTag,
  useAiFacets,
  useAiTags,
  useMailSummary,
  useResearch,
  useThemes,
} from "../../api/queries";
import {
  BULK_LIMIT,
  MAX_FACET_LIMIT,
  type AiFacets as Facets,
  type AiTagCount,
  type MailFilters,
} from "../../api/types";
import { Button } from "../../components/Button";
import { FoldHeading } from "../../components/FoldCard";
import { cx } from "../../lib/cx";
import { useFold } from "../../lib/folds";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { mailsText } from "../entities/labels";
import { Dialog } from "../persons/Dialog";
import styles from "./AiFacets.module.css";
import type { ChipNames } from "./chips";
import { columnWide, facetScope, subscribeWidth, useClipped } from "./EntityFacets";
import facets from "./EntityFacets.module.css";
import { toFilters, withFilters, type ListState } from "./listState";

type Placement = "column" | "top";

/** The AI tags and themes of the list's mails (D309): two panels "KI-Schlagwörter" and
 *  "KI-Themen" under the entity facets, beside the table or above it, counted as they are
 *  (D87), each folding by its heading. A click adds a tag or theme to the filter, a second one
 *  takes it out; a tag's quiet action gives the team tag of its name to its mails (D310). Both
 *  are marked machine made (D311). A panel without entries is left out, so an archive without
 *  summaries looks as before. Mounted at both places; each renders only at its widths. */
export function AiFacets({
  state,
  onChange,
  onNotice,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  /** The notice after a tag was adopted, which the list shows above the table. */
  onNotice: (text: string) => void;
  placement: Placement;
}) {
  const wide = useSyncExternalStore(subscribeWidth, columnWide, () => false);
  if (wide !== (placement === "column")) return null;
  return <AiPanels state={state} onChange={onChange} onNotice={onNotice} placement={placement} />;
}

function AiPanels({
  state,
  onChange,
  onNotice,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  onNotice: (text: string) => void;
  placement: Placement;
}) {
  const filters = toFilters(state);
  const counts = useAiFacets(filters);
  const summary = useMailSummary(filters);
  const themes = useThemes();
  const [adopting, setAdopting] = useState<AiTagCount | null>(null);
  const data = counts.data;
  if (!data) return null;
  const total = summary.data?.exact ? summary.data.total : null;
  const scope = facetScope(data, total);
  const stale = counts.isPlaceholderData;
  const toggleTag = (id: number) =>
    onChange(withFilters(state, { ai_tag: toggled(state.ai_tag, id) }));
  const toggleTheme = (key: string) =>
    onChange(withFilters(state, { ai_theme: toggled(state.ai_theme, key) }));

  return (
    <>
      {data.tags.length > 0 && (
        <Panel id="mails.ai-tags" title="KI-Schlagwörter" scope={scope} placement={placement}>
          <Chips placement={placement} stale={stale} content={data.tags}>
            {data.tags.map((tag) => {
              const selected = state.ai_tag.includes(tag.id);
              return (
                <li key={tag.id} className={cx(facets.chip, selected && facets.selected)}>
                  <button
                    type="button"
                    className={facets.toggle}
                    aria-pressed={selected}
                    title={
                      selected
                        ? `KI-Schlagwort · im Filter; Klick nimmt es heraus`
                        : `KI-Schlagwort · ${mailsText(tag.mails)}; Klick grenzt die Liste ein`
                    }
                    onClick={() => toggleTag(tag.id)}
                  >
                    <span className={facets.label}>{tag.label}</span>{" "}
                    <span className={facets.count}>{formatNumber(tag.mails)}</span>
                  </button>
                  <button
                    type="button"
                    className={cx(facets.open, styles.adopt)}
                    aria-label={`„${tag.label}“ als Team-Tag übernehmen`}
                    title={`Als Team-Tag übernehmen: „${tag.label}“ als Schlagwort des Teams an diese Mails vergeben`}
                    onClick={() => setAdopting(tag)}
                  >
                    <TagMark />
                  </button>
                </li>
              );
            })}
          </Chips>
        </Panel>
      )}
      {data.themes.length > 0 && (
        <Panel id="mails.ai-themes" title="KI-Themen" scope={scope} placement={placement}>
          <Chips placement={placement} stale={stale} content={data.themes}>
            {data.themes.map((theme) => {
              const selected = state.ai_theme.includes(theme.key);
              const color = themes.data?.find((other) => other.key === theme.key)?.color;
              return (
                <li key={theme.key} className={cx(facets.chip, selected && facets.selected)}>
                  <button
                    type="button"
                    className={cx(facets.toggle, styles.alone)}
                    aria-pressed={selected}
                    title={
                      selected
                        ? `Hinweis auf ${theme.label} · im Filter; Klick nimmt es heraus`
                        : `Hinweis auf ${theme.label} in ${mailsText(theme.mails)}; Klick grenzt die Liste ein`
                    }
                    onClick={() => toggleTheme(theme.key)}
                  >
                    {color && (
                      <span
                        className={facets.dot}
                        style={{ background: TAG_PALETTE[color].text }}
                        aria-hidden="true"
                      />
                    )}
                    <span className={facets.label}>{theme.label}</span>{" "}
                    <span className={facets.count}>{formatNumber(theme.mails)}</span>
                  </button>
                </li>
              );
            })}
          </Chips>
        </Panel>
      )}
      {adopting && (
        <AdoptDialog
          tag={adopting}
          facets={data}
          filters={filters}
          onDone={onNotice}
          onClose={() => setAdopting(null)}
        />
      )}
    </>
  );
}

function toggled<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((other) => other !== value) : [...values, value];
}

/** One panel: its heading folds it, remembered in this browser (lib/folds); the mark "maschinell
 *  erzeugt" and the scope of the counts beside it. */
function Panel({
  id,
  title,
  scope,
  placement,
  children,
}: {
  id: string;
  title: string;
  scope: string;
  placement: Placement;
  children: ReactNode;
}) {
  const [open, setOpen] = useFold(id, true);
  const titleId = useId();
  const bodyId = useId();
  return (
    <section
      className={cx(facets.panel, facets[placement], styles[placement], !open && facets.closed)}
      aria-labelledby={titleId}
    >
      <div className={facets.head}>
        <FoldHeading
          id={titleId}
          open={open}
          controls={open ? bodyId : undefined}
          onToggle={() => setOpen(!open)}
        >
          {title}
        </FoldHeading>
        <span className={cx(facets.scope, styles.scope)}>
          <span className={styles.machine} title="Von einem Sprachmodell vergeben; kann irren">
            maschinell erzeugt
          </span>
          {open && scope}
        </span>
      </div>
      {open && (
        <div id={bodyId} className={styles.body}>
          {children}
        </div>
      )}
    </section>
  );
}

/** The chips of a panel: they wrap in the column; above the table they are one line with "mehr"
 *  beside it while some are hidden, as the signal facets are. */
function Chips({
  placement,
  stale,
  content,
  children,
}: {
  placement: Placement;
  stale: boolean;
  content: { mails: number }[];
  children: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const list = useRef<HTMLUListElement>(null);
  const clip = placement === "top" && !expanded;
  const clipped = useClipped(list, clip, content.map((entry) => entry.mails).join());
  return (
    <div className={cx(styles.row, placement === "top" && styles.line, stale && facets.stale)}>
      <ul ref={list} className={cx(facets.chips, clip && facets.clipped)}>
        {children}
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
  );
}

/** A small tag: the quiet action of adopting an AI tag. */
function TagMark() {
  return (
    <svg
      width={12}
      height={12}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z" />
      <circle cx="8" cy="8" r="1.5" />
    </svg>
  );
}

/** "Team-Tag „Spende“ an 3 Mails vergeben" (D310). */
export function adoptedText(label: string, mails: number): string {
  return mails === 0
    ? `Diese Mails tragen den Team-Tag „${label}“ schon`
    : `Team-Tag „${label}“ an ${mailsText(mails)} vergeben`;
}

/** Asks before the team tag of an AI tag's name goes to its mails (D310): without filters every
 *  mail carrying it (hidden ones too, as the unfiltered facet counts them), else the list's mails
 *  carrying it, as many as the list's summary counts with the tag added. */
function AdoptDialog({
  tag,
  facets: counted,
  filters,
  onDone,
  onClose,
}: {
  tag: AiTagCount;
  facets: Facets;
  filters: MailFilters;
  onDone: (notice: string) => void;
  onClose: () => void;
}) {
  const props = { tag, onDone, onClose };
  // The facets say whether they counted every mail (D202) or the list's.
  if (counted.mails === null) return <AdoptConfirm {...props} total={tag.mails} />;
  return <FilteredAdopt {...props} filters={filters} />;
}

function FilteredAdopt({
  filters,
  ...props
}: {
  tag: AiTagCount;
  filters: MailFilters;
  onDone: (notice: string) => void;
  onClose: () => void;
}) {
  const summary = useMailSummary({ ...filters, ai_tag: [...(filters.ai_tag ?? []), props.tag.id] });
  return (
    <AdoptConfirm
      {...props}
      filters={filters}
      total={summary.data?.total ?? null}
      lower={summary.data?.exact === false}
      counting={summary.isPending}
    />
  );
}

function AdoptConfirm({
  tag,
  filters,
  total,
  lower = false,
  counting = false,
  onDone,
  onClose,
}: {
  tag: AiTagCount;
  /** The list's filters; none: every mail carrying the tag. */
  filters?: MailFilters;
  /** The mails that get the tag, at least that many when lower; null when not known. */
  total: number | null;
  lower?: boolean;
  counting?: boolean;
  onDone: (notice: string) => void;
  onClose: () => void;
}) {
  const research = useResearch();
  const adopt = useAdoptAiTag();
  const known = research.data?.tags.some(
    (team) => team.name.toLowerCase() === tag.label.toLowerCase(),
  );
  const tooMany = total !== null && total > BULK_LIMIT;
  const count = total === null ? "die Mails" : `${lower ? "mehr als " : ""}${mailsText(total)}`;

  return (
    <Dialog title="Als Team-Tag übernehmen?" onClose={onClose}>
      <p className={styles.text}>
        {filters
          ? `Der Team-Tag „${tag.label}“ geht an ${count} dieser Liste, die das KI-Schlagwort tragen.`
          : `Der Team-Tag „${tag.label}“ geht an ${count} mit diesem KI-Schlagwort, ausgeblendete eingeschlossen.`}{" "}
        {known ? "Es gibt ihn schon unter den Schlagwörtern." : "Er wird neu angelegt."}
      </p>
      <p className={styles.hint}>
        Danach ist er ein Schlagwort des Teams wie jedes andere und bleibt, auch wenn die
        Zusammenfassung später verworfen wird.
      </p>
      {tooMany && (
        <p className={styles.warning} role="alert">
          {`Höchstens ${formatNumber(BULK_LIMIT)} Mails auf einmal; bitte die Liste eingrenzen.`}
        </p>
      )}
      {adopt.error && (
        <p className={styles.warning} role="alert">
          {adoptErrorText(adopt.error)}
        </p>
      )}
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button
          variant="primary"
          disabled={adopt.isPending || counting || tooMany}
          onClick={() =>
            adopt.mutate(filters ? { tagId: tag.id, filters } : { tagId: tag.id }, {
              onSuccess: (result) => {
                onDone(adoptedText(tag.label, result.mails));
                onClose();
              },
            })
          }
        >
          Übernehmen
        </Button>
      </div>
    </Dialog>
  );
}

function adoptErrorText(error: Error): string {
  if (error instanceof ApiError) {
    if (error.code === "too_many_mails") {
      return `Höchstens ${formatNumber(BULK_LIMIT)} Mails auf einmal; bitte die Liste eingrenzen.`;
    }
    if (error.code === "empty_selection") return "Keine dieser Mails trägt das KI-Schlagwort noch.";
    if (error.code === "not_found") return "Dieses KI-Schlagwort gibt es nicht mehr.";
  }
  return "Das hat nicht geklappt. Bitte noch einmal versuchen.";
}

/** Names for the chips of the AI filters (D309): the tags' labels, asked for in one request,
 *  and the themes' names and colours; undefined while they load. */
export function useAiChipNames(ids: number[]): Pick<ChipNames, "aiTag" | "aiTheme"> {
  const tags = useAiTags({ id: ids, limit: MAX_FACET_LIMIT }, ids.length > 0);
  const themes = useThemes();
  return {
    aiTag: (id) => tags.data?.find((tag) => tag.id === id)?.label,
    aiTheme: (key) => {
      const theme = themes.data?.find((other) => other.key === key);
      return theme && { name: theme.name, color: theme.color };
    },
  };
}
