import { Link } from "react-router";

import type { DocumentDetail } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { photoPosition, PhotoPosition } from "../places/PhotoPosition";
import {
  coordinates,
  GROUP_LABELS,
  METADATA_GROUPS,
  METADATA_STATUS_TEXTS,
  metadataRows,
  openStreetMapUrl,
  type MetadataRow,
} from "./metadata";
import styles from "./MetadataCard.module.css";
import { metadataListHref } from "./urlState";

/** What the file says about itself (D167): every field found, in groups, as found and never
 *  rated, with the place on a small map and OpenStreetMap (D249) and the document list of its
 *  author and program. */
export function MetadataCard({ document }: { document: DocumentDetail }) {
  const { metadata } = document;
  const rows = metadataRows(metadata);
  const place = coordinates(metadata);
  const summary = metadata.summary;
  const position = photoPosition(summary);
  const groups = METADATA_GROUPS.filter(
    (group) => rows.some((row) => row.group === group) || (group === "place" && place),
  );

  return (
    <Card variant="side" aria-labelledby="document-metadata-title">
      <CardTitle id="document-metadata-title" variant="caps">
        Metadaten
      </CardTitle>
      {metadata.status === "pending" ? (
        <p className={styles.status}>
          Noch nicht gelesen: beim nächsten Import-Lauf unter <Link to="/import">Import</Link>.
        </p>
      ) : metadata.status !== "found" ? (
        <>
          <p className={styles.status}>{METADATA_STATUS_TEXTS[metadata.status]}</p>
          {metadata.error && <code className={styles.error}>{metadata.error}</code>}
        </>
      ) : (
        <>
          {groups.map((group) => (
            <section
              key={group}
              className={styles.group}
              aria-labelledby={`document-metadata-${group}`}
            >
              <h3 id={`document-metadata-${group}`} className={styles.groupTitle}>
                {GROUP_LABELS[group]}
              </h3>
              {group === "place" && position && (
                <PhotoPosition documentId={document.id} position={position} openStreetMap={false} />
              )}
              <dl className={styles.fields}>
                {group === "place" && place && (
                  <div className={styles.field}>
                    <dt>
                      Koordinaten <span className={styles.source}>GPS</span>
                    </dt>
                    <dd>
                      <span className={styles.value}>
                        {`${place.latitude}, ${place.longitude}`}
                      </span>{" "}
                      <a
                        href={openStreetMapUrl(place)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={styles.map}
                      >
                        auf OpenStreetMap ansehen
                      </a>
                    </dd>
                  </div>
                )}
                {rows
                  .filter((row) => row.group === group)
                  .map((row) => (
                    <Field key={row.id} row={row} />
                  ))}
              </dl>
            </section>
          ))}
          {metadata.error && (
            <p className={styles.damaged}>
              {metadata.error.startsWith("encrypted")
                ? "Die Datei ist verschlüsselt; aufgeführt ist, was sich ohne Kennwort lesen ließ."
                : "Ein Teil der Datei ist beschädigt; aufgeführt ist, was sich davor lesen ließ."}{" "}
              <code className={styles.error}>{metadata.error}</code>
            </p>
          )}
          {(summary?.author || summary?.software) && (
            <ul className={styles.links}>
              {summary.author && (
                <li>
                  <Link to={metadataListHref("author", summary.author)}>
                    Alle Dokumente dieses Autors
                  </Link>
                </li>
              )}
              {summary.software && (
                <li>
                  <Link to={metadataListHref("program", summary.software)}>
                    Alle Dokumente dieses Programms
                  </Link>
                </li>
              )}
            </ul>
          )}
          <p className={styles.note}>
            So steht es in der Datei. Mailrobbe prüft diese Angaben nicht; sie können falsch oder
            gefälscht sein.
          </p>
        </>
      )}
    </Card>
  );
}

function Field({ row }: { row: MetadataRow }) {
  return (
    <div className={styles.field}>
      <dt>
        {row.label} <span className={styles.source}>{row.source}</span>
      </dt>
      <dd className={styles.value} title={row.title}>
        {row.value}
      </dd>
    </div>
  );
}
