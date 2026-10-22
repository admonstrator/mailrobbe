import { useState, type FormEvent, type ReactNode } from "react";

import { useMboxFiles, useResearch, useStats } from "../../api/queries";
import type { PlaceSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { Chip } from "../../components/Chip";
import { SearchIcon } from "../../components/icons";
import { formatNumber, utcDay } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { PersonField } from "../documents/PersonField";
import { filterChips } from "../mails/chips";
import { DateField } from "../mails/FilterColumn";
import { FilterGroup } from "../mails/FilterGroup";
import { withFilters, type FilterPatch } from "../mails/listState";
import { useSignalChipNames } from "../mails/SignalFacets";
import { LAYER_HINTS, LAYER_LABELS } from "./labels";
import { MAP_COLORS } from "./mapStyle";
import styles from "./PlaceFilters.module.css";
import { DEFAULT_PLACES_STATE, LAYER_KEYS, type LayerKey, type PlacesState } from "./urlState";

/** A layer's figures for its switch: the points it has (undefined while loading), and what it
 *  leaves out. */
export interface LayerInfo {
  count: number | undefined;
  notice: string | null;
  failed: boolean;
}

type Period = "taken" | "sent";

/** The filter column of the page "Orte" (D247): the search, the three layers, the period by
 *  capture time or by date sent, person, device and Akte; the mail list's other filters, which
 *  come with "Auf der Karte", as chips. Below them, children (the card "Kartendaten"). */
export function PlaceFilters({
  state,
  onChange,
  layers,
  summary,
  children,
}: {
  state: PlacesState;
  onChange: (next: PlacesState) => void;
  layers: Record<LayerKey, LayerInfo>;
  summary: PlaceSummary | undefined;
  children?: ReactNode;
}) {
  const { list } = state;
  const stats = useStats();
  const research = useResearch();
  const mboxFiles = useMboxFiles();
  const signalNames = useSignalChipNames();
  const [period, setPeriod] = useState<Period>(
    (list.date_from || list.date_to) && !(state.taken_from || state.taken_to) ? "sent" : "taken",
  );
  const change = (patch: FilterPatch) => onChange({ ...state, list: withFilters(list, patch) });

  // One person with a role of the field (sent, received); more, or Cc only, stay chips.
  const personField =
    list.person.length <= 1 && list.between.length === 0 && list.person_role !== "cc";
  const collections = research.data?.collections ?? [];
  const akteField = list.collection.length <= 1;
  const shownHere = (id: string) =>
    id === "q" ||
    id === "date" ||
    (personField && id.startsWith("person-")) ||
    (akteField && id.startsWith("collection-"));
  const chips = filterChips(list, [], {
    person: (id) => `#${id}`,
    mboxFile: (id) => mboxFiles.data?.find((file) => file.id === id)?.path ?? `Datei #${id}`,
    tag: (id) => research.data?.tags.find((tag) => tag.id === id),
    collection: (id) => collections.find((other) => other.id === id)?.name,
    signal: signalNames,
  }).filter((chip) => !shownHere(chip.id));

  const from = period === "taken" ? state.taken_from : list.date_from;
  const to = period === "taken" ? state.taken_to : list.date_to;
  const dayMin =
    period === "sent" && stats.data?.date_min ? utcDay(stats.data.date_min) : undefined;
  const dayMax =
    period === "sent" && stats.data?.date_max ? utcDay(stats.data.date_max) : undefined;
  function setDays(next: { from: string | null; to: string | null }) {
    if (period === "taken") onChange({ ...state, taken_from: next.from, taken_to: next.to });
    else change({ date_from: next.from, date_to: next.to });
  }
  /** The days chosen move to the other kind of period. */
  function switchPeriod(next: Period) {
    setPeriod(next);
    if (next === period || (!from && !to)) return;
    onChange(
      next === "sent"
        ? {
            ...state,
            taken_from: null,
            taken_to: null,
            list: withFilters(list, { date_from: from, date_to: to }),
          }
        : {
            ...state,
            taken_from: from,
            taken_to: to,
            list: withFilters(list, { date_from: null, date_to: null }),
          },
    );
  }

  const devices = summary?.devices ?? [];
  const deviceKnown = state.device === null || devices.some((one) => one.device === state.device);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    change({ q });
  }

  return (
    <aside className={styles.column} aria-label="Filter">
      <div className={styles.head}>
        <h2 className={styles.heading}>Filter</h2>
        <Button
          variant="link"
          onClick={() =>
            onChange({ ...DEFAULT_PLACES_STATE, off: state.off, view: state.view, point: null })
          }
        >
          Zurücksetzen
        </Button>
      </div>

      <form role="search" className={styles.search} onSubmit={onSearch}>
        <SearchIcon className={styles.searchIcon} />
        <label htmlFor="places-search" className="sr-only">
          Mails durchsuchen
        </label>
        <input
          key={list.q}
          id="places-search"
          name="q"
          type="search"
          defaultValue={list.q}
          placeholder="Suche wie in der Mailliste …"
          autoComplete="off"
          spellCheck={false}
          className={styles.searchInput}
        />
      </form>

      {chips.length > 0 && (
        <div className={styles.chips} role="group" aria-label="Weitere Filter">
          {chips.map((chip) => (
            <Chip
              key={chip.id}
              label={chip.label}
              color={chip.color && TAG_PALETTE[chip.color].text}
              onRemove={() => onChange({ ...state, list: chip.next })}
            />
          ))}
        </div>
      )}

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Ebenen</legend>
        {LAYER_KEYS.map((key) => (
          <LayerSwitch
            key={key}
            layer={key}
            info={layers[key]}
            on={!state.off.includes(key)}
            onChange={(on) =>
              onChange({
                ...state,
                off: LAYER_KEYS.filter((other) =>
                  other === key ? !on : state.off.includes(other),
                ),
              })
            }
          />
        ))}
      </fieldset>

      <FilterGroup id="places.period" title="Zeitraum" active={Boolean(from || to)}>
        <select
          aria-label="Zeitraum nach"
          className={styles.select}
          value={period}
          onChange={(event) => switchPeriod(event.target.value as Period)}
        >
          <option value="taken">nach Aufnahmezeit der Fotos</option>
          <option value="sent">nach Sendedatum der Mails</option>
        </select>
        <div className={styles.dates}>
          <DateField
            key={`${period}-from`}
            id="places-date-from"
            label="von"
            value={from}
            min={dayMin}
            max={to ?? dayMax}
            onCommit={(day) => setDays({ from: day, to })}
          />
          <DateField
            key={`${period}-to`}
            id="places-date-to"
            label="bis"
            value={to}
            min={from ?? dayMin}
            max={dayMax}
            onCommit={(day) => setDays({ from, to: day })}
          />
        </div>
        {period === "taken" && (
          <p className={styles.hint}>
            Gilt nur für Fotos; Aufnahmezeiten ohne Zeitzone zählen hier nicht.
          </p>
        )}
      </FilterGroup>

      {personField && (
        <PersonField
          person={list.person[0] ?? null}
          role={list.person_role === "cc" ? null : list.person_role}
          onChange={(person, person_role) =>
            change({ person: person === null ? [] : [person], person_role })
          }
        />
      )}

      <FilterGroup id="places.device" title="Gerät" active={state.device !== null}>
        <select
          aria-label="Gerät"
          className={styles.select}
          value={state.device ?? ""}
          onChange={(event) => onChange({ ...state, device: event.target.value || null })}
        >
          <option value="">alle Geräte</option>
          {!deviceKnown && state.device && <option value={state.device}>{state.device}</option>}
          {devices.map((one) => (
            <option key={one.device} value={one.device}>
              {`${one.device} (${formatNumber(one.photos)})`}
            </option>
          ))}
        </select>
      </FilterGroup>

      {akteField && (collections.length > 0 || list.collection.length > 0) && (
        <FilterGroup id="places.collection" title="Akte" active={list.collection.length > 0}>
          <select
            aria-label="Akte"
            className={styles.select}
            value={list.collection[0] ?? ""}
            onChange={(event) =>
              change({ collection: event.target.value ? [Number(event.target.value)] : [] })
            }
          >
            <option value="">alle Mails</option>
            {list.collection.length > 0 &&
              !collections.some((one) => one.id === list.collection[0]) && (
                <option value={list.collection[0]}>{`Akte #${list.collection[0]}`}</option>
              )}
            {collections.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </FilterGroup>
      )}

      {children}
    </aside>
  );
}

/** A layer's switch with its colour and count, and what the layer leaves out. */
function LayerSwitch({
  layer,
  info,
  on,
  onChange,
}: {
  layer: LayerKey;
  info: LayerInfo;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <div className={styles.layer}>
      <Checkbox checked={on} onChange={onChange} count={info.count} title={LAYER_HINTS[layer]}>
        <span
          className={styles.swatch}
          style={{ background: MAP_COLORS[layer] }}
          aria-hidden="true"
        />
        {LAYER_LABELS[layer]}
      </Checkbox>
      {info.failed && <p className={styles.layerNote}>Lässt sich gerade nicht laden.</p>}
      {info.notice && <p className={styles.layerNote}>{info.notice}</p>}
    </div>
  );
}
