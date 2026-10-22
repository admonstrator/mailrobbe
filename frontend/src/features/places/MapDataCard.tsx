import { useId, useState } from "react";

import {
  useDeleteDetailMap,
  useMapStatus,
  useStartMapDownload,
  useStopMapDownload,
} from "../../api/queries";
import {
  type BBox,
  type DetailMap,
  type MapDetailKey,
  type MapDownloadRequest,
  type MapJob,
  type MapPartial,
  type MapRegionKey,
  type MapStatus,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatBytes, formatDate, formatDateTime } from "../../lib/format";
import { StepList } from "../import/StepList";
import { Dialog } from "../persons/Dialog";
import { DETAIL_HINTS, DETAIL_LABELS, mapErrorText, REGION_LABELS } from "./labels";
import styles from "./MapDataCard.module.css";
import { roundDegrees } from "./urlState";

const REGION_KEYS: readonly MapRegionKey[] = ["de", "at", "ch", "dach", "view"];
const DETAIL_KEYS: readonly MapDetailKey[] = ["overview", "streets", "full"];

/** A download fails at once with less free space than its size and 5 % more (D246). */
const SPACE_MARGIN = 1.05;

/** The map's view as a region to download: within the world, rounded like the URL. */
export function viewBBox([west, south, east, north]: BBox): BBox {
  const clamp = (value: number, limit: number) => Math.max(-limit, Math.min(limit, value));
  return [
    roundDegrees(clamp(west, 180)),
    roundDegrees(clamp(south, 85)),
    roundDegrees(clamp(east, 180)),
    roundDegrees(clamp(north, 85)),
  ];
}

/** The size of a choice when it is known beforehand: the presets' sizes on the build of
 *  size_hints_build; the view's is measured when the run starts. */
export function choiceSize(
  status: MapStatus,
  region: MapRegionKey,
  detail: MapDetailKey,
): number | null {
  return status.regions.find((info) => info.key === region)?.sizes[detail] ?? null;
}

const choiceText = (region: MapRegionKey, detail: MapDetailKey) =>
  `${REGION_LABELS[region]}, ${DETAIL_LABELS[detail]}`;

/** The card "Kartendaten" (D245, D246): the detail map there is, a download running or stopped,
 *  and the choice of a new one, offered only when the server offers downloads. */
export function MapDataCard({ view }: { view: BBox | null }) {
  const titleId = useId();
  const status = useMapStatus();
  const [error, setError] = useState<string | null>(null);

  if (status.isPending) return null;
  if (status.isError) {
    return (
      <section className={styles.card} aria-labelledby={titleId}>
        <h2 id={titleId} className={styles.title}>
          Kartendaten
        </h2>
        <p className={styles.error} role="alert">
          Der Stand der Kartendaten lässt sich nicht laden.
        </p>
      </section>
    );
  }
  const data = status.data;
  const job = data.job;
  const alive = job?.alive ?? false;
  if (!data.offered && !data.detail_map && !data.partial && !alive) return null;

  return (
    <section className={styles.card} aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.title}>
        Kartendaten
      </h2>
      <DetailMapInfo detail={data.detail_map} onError={setError} busy={alive} />
      {job && alive && <MapRun job={job} onError={setError} />}
      {job && !alive && <EndedRun job={job} />}
      {!alive && data.partial && (
        <PartialInfo partial={data.partial} offered={data.offered} onError={setError} />
      )}
      {!alive && data.offered && <DownloadForm status={data} view={view} onError={setError} />}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** The detail map there is, with its delete. Without one, the overview alone. */
function DetailMapInfo({
  detail,
  busy,
  onError,
}: {
  detail: DetailMap | null;
  busy: boolean;
  onError: (message: string | null) => void;
}) {
  const [asking, setAsking] = useState(false);
  if (!detail) {
    return (
      <p className={styles.text}>
        Die Karte zeigt den mitgelieferten Überblick: Länder, Regionen, Gewässer und größere Orte.
      </p>
    );
  }
  return (
    <div className={styles.detail}>
      <p className={styles.text}>
        <span className={styles.strong}>
          Detailkarte: {choiceText(detail.region, detail.detail)}
        </span>
        <br />
        {`${formatBytes(detail.size)} · geladen am ${formatDate(detail.downloaded_at)}`}
        {detail.build && ` · OpenStreetMap-Stand ${detail.build}`}
      </p>
      <Button
        variant="link"
        size="xs"
        className={styles.delete}
        disabled={busy}
        title={busy ? "Erst nach dem laufenden Download" : undefined}
        onClick={() => setAsking(true)}
      >
        Detailkarte löschen
      </Button>
      {asking && (
        <DeleteDialog
          what={`Die Detailkarte (${choiceText(detail.region, detail.detail)}, ${formatBytes(detail.size)})`}
          onClose={() => setAsking(false)}
          onError={onError}
        />
      )}
    </div>
  );
}

/** Asks before the detail map and a stopped download's part are deleted. */
function DeleteDialog({
  what,
  onClose,
  onError,
}: {
  what: string;
  onClose: () => void;
  onError: (message: string | null) => void;
}) {
  const remove = useDeleteDetailMap();
  return (
    <Dialog title="Detailkarte löschen?" onClose={onClose}>
      <div className={styles.dialog}>
        <p className={styles.text}>
          {what} wird auf dem Server gelöscht, mit einem angehaltenen Download. Die Karte zeigt
          danach wieder den mitgelieferten Überblick; eine Detailkarte lässt sich jederzeit neu
          laden.
        </p>
        {remove.error && (
          <p className={styles.error} role="alert">
            {mapErrorText(remove.error, "delete")}
          </p>
        )}
        <div className={styles.dialogFoot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button
            variant="primary"
            disabled={remove.isPending}
            onClick={() =>
              remove.mutate(undefined, {
                onSuccess: () => {
                  onError(null);
                  onClose();
                },
              })
            }
          >
            Löschen
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** A download while it runs: its choice, its bytes and steps (D246), and "Anhalten". */
function MapRun({ job, onError }: { job: MapJob; onError: (message: string | null) => void }) {
  const stop = useStopMapDownload();
  const { progress, options } = job;
  const total = progress.bytes_total;
  return (
    <div className={styles.run} role="group" aria-label="Download der Detailkarte">
      <p className={styles.runTitle}>
        <Spinner label="Läuft" />
        {job.stop_requested ? "Download wird angehalten …" : "Download läuft"}
      </p>
      <p className={styles.text}>
        {choiceText(options.region, options.detail)}
        <br />
        {total === null
          ? `${formatBytes(progress.bytes_done)} geladen`
          : `${formatBytes(progress.bytes_done)} von ${formatBytes(total)}`}
        {progress.continued_bytes > 0 &&
          `, davon ${formatBytes(progress.continued_bytes)} aus einem früheren Lauf`}
        {job.origin === "cli" && " · über die Kommandozeile gestartet"}
      </p>
      <StepList
        steps={progress.steps}
        alive
        age={job.report_age_seconds}
        database={progress.database}
      />
      <Button
        size="sm"
        className={styles.action}
        disabled={job.stop_requested || stop.isPending}
        onClick={() =>
          stop.mutate(undefined, {
            onSuccess: () => onError(null),
            onError: (error) => onError(mapErrorText(error, "stop")),
          })
        }
      >
        {job.stop_requested ? "Wird angehalten …" : "Anhalten"}
      </Button>
    </div>
  );
}

/** How the latest download ended, when it did not simply finish: its reason when it failed. */
function EndedRun({ job }: { job: MapJob }) {
  if (job.status === "done" || job.status === "stopped") return null;
  // "running" without a living process: it ended without recording it (D47).
  return (
    <div className={styles.failed} role="status">
      <p className={styles.text}>
        <span className={styles.strong}>Der letzte Download ist abgebrochen</span>
        {` (${choiceText(job.options.region, job.options.detail)}, ${formatDateTime(job.finished_at ?? job.updated_at)}).`}
      </p>
      {job.message && <code className={styles.message}>{job.message}</code>}
    </div>
  );
}

/** A stopped download, which the same choice continues (D246). */
function PartialInfo({
  partial,
  offered,
  onError,
}: {
  partial: MapPartial;
  offered: boolean;
  onError: (message: string | null) => void;
}) {
  const start = useStartMapDownload();
  const [asking, setAsking] = useState(false);
  const request: MapDownloadRequest = {
    region: partial.region,
    detail: partial.detail,
    ...(partial.region === "view" ? { bbox: partial.bbox } : {}),
  };
  return (
    <div className={styles.partial}>
      <p className={styles.text}>
        <span className={styles.strong}>Angehaltener Download</span>:{" "}
        {choiceText(partial.region, partial.detail)}
        <br />
        {`${formatBytes(partial.bytes_done)} von ${formatBytes(partial.bytes_total)} geladen`}
      </p>
      <div className={styles.actions}>
        {offered && (
          <Button
            size="sm"
            variant="primary"
            disabled={start.isPending}
            onClick={() =>
              start.mutate(request, {
                onSuccess: () => onError(null),
                onError: (error) => onError(mapErrorText(error)),
              })
            }
          >
            Fortsetzen
          </Button>
        )}
        <Button size="sm" variant="link" onClick={() => setAsking(true)}>
          Verwerfen
        </Button>
      </div>
      {asking && (
        <DeleteDialog
          what={`Der angehaltene Download (${formatBytes(partial.bytes_done)})`}
          onClose={() => setAsking(false)}
          onError={onError}
        />
      )}
    </div>
  );
}

/** The choice of a detail map: region and detail with their sizes, the free space, and where
 *  the data comes from. With a detail map there already, behind "Andere Detailkarte laden". */
function DownloadForm({
  status,
  view,
  onError,
}: {
  status: MapStatus;
  view: BBox | null;
  onError: (message: string | null) => void;
}) {
  const start = useStartMapDownload();
  const [open, setOpen] = useState(false);
  const [region, setRegion] = useState<MapRegionKey>(status.detail_map?.region ?? "de");
  const [detail, setDetail] = useState<MapDetailKey>("streets");
  // With a detail map or a stopped download (continued above) a new choice is a second step.
  const replaces = status.detail_map !== null || status.partial !== null;
  if (replaces && !open) {
    return (
      <Button variant="link" size="xs" className={styles.more} onClick={() => setOpen(true)}>
        Andere Detailkarte laden …
      </Button>
    );
  }

  const size = choiceSize(status, region, detail);
  const free = status.free_bytes;
  const tooLarge = size !== null && free !== null && size * SPACE_MARGIN > free;
  const noView = region === "view" && view === null;
  const sizeText = (key: MapRegionKey, level: MapDetailKey) => {
    const known = choiceSize(status, key, level);
    return known === null ? "Größe wird beim Start ermittelt" : formatBytes(known);
  };
  const maxZoom = (level: MapDetailKey) =>
    status.details.find((info) => info.key === level)?.max_zoom;

  function onStart() {
    const request: MapDownloadRequest = { region, detail };
    if (region === "view" && view) request.bbox = viewBBox(view);
    start.mutate(request, {
      onSuccess: () => {
        onError(null);
        setOpen(false);
      },
      onError: (error) => onError(mapErrorText(error)),
    });
  }

  return (
    <form
      className={styles.form}
      aria-label="Detailkarte laden"
      onSubmit={(event) => {
        event.preventDefault();
        onStart();
      }}
    >
      <fieldset className={styles.choices}>
        <legend className={styles.legend}>Region</legend>
        {REGION_KEYS.map((key) => (
          <label key={key} className={styles.choice}>
            <input
              type="radio"
              name="map-region"
              value={key}
              checked={region === key}
              onChange={() => setRegion(key)}
            />
            <span className={styles.choiceLabel}>{REGION_LABELS[key]}</span>
            <span className={styles.size}>{sizeText(key, detail)}</span>
          </label>
        ))}
      </fieldset>
      <fieldset className={styles.choices}>
        <legend className={styles.legend}>Detail</legend>
        {DETAIL_KEYS.map((key) => (
          <label key={key} className={styles.choice} title={DETAIL_HINTS[key]}>
            <input
              type="radio"
              name="map-detail"
              value={key}
              checked={detail === key}
              onChange={() => setDetail(key)}
            />
            <span className={styles.choiceLabel}>
              {DETAIL_LABELS[key]}
              <span className={styles.hint}>
                {DETAIL_HINTS[key]}
                {maxZoom(key) !== undefined && `, bis Zoomstufe ${maxZoom(key)}`}
              </span>
            </span>
            <span className={styles.size}>{sizeText(region, key)}</span>
          </label>
        ))}
      </fieldset>
      <p className={styles.text}>
        {free === null
          ? "Freier Platz auf dem Server unbekannt"
          : `Frei auf dem Server: ${formatBytes(free)}`}
        {size !== null &&
          status.size_hints_build &&
          ` · Größen vom Stand ${status.size_hints_build}`}
      </p>
      {tooLarge && (
        <p className={styles.warning}>Dafür reicht der freie Platz auf dem Server nicht.</p>
      )}
      <p className={styles.note}>
        Mailrobbe lädt dafür einmal Kartendaten aus OpenStreetMap von{" "}
        <span className={styles.host}>{status.source_host ?? "der eingestellten Quelle"}</span>;
        sonst geht nichts ins Internet.
      </p>
      {status.detail_map && (
        <p className={styles.note}>
          Eine neue Detailkarte ersetzt die vorhandene, sobald sie vollständig ist.
        </p>
      )}
      {status.partial && (
        <p className={styles.note}>
          Eine andere Auswahl beginnt von vorn; der angehaltene Download wird dann verworfen.
        </p>
      )}
      <div className={styles.actions}>
        <Button
          type="submit"
          size="sm"
          variant="primary"
          disabled={start.isPending || tooLarge || noView}
        >
          Detailkarte laden
        </Button>
        {replaces && (
          <Button size="sm" variant="link" onClick={() => setOpen(false)}>
            Abbrechen
          </Button>
        )}
      </div>
    </form>
  );
}
