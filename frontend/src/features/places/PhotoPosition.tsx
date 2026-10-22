import { lazy, Suspense } from "react";
import { Link } from "react-router";

import type { MetadataSummary } from "../../api/types";
import { openStreetMapUrl } from "../../lib/osm";
import styles from "./PhotoPosition.module.css";
import { photoPlacesHref } from "./urlState";

// MapLibre comes in the chunk of the page "Orte"; the small maps load it only when they show.
const SmallMap = lazy(() => import("./SmallMap").then((module) => ({ default: module.SmallMap })));

export interface Position {
  lat: number;
  lon: number;
}

/** The position a file states (D241), which the small map shows: none without both
 *  coordinates, and none at exactly 0, 0, which some cameras write without a fix. */
export function photoPosition(summary: MetadataSummary | null | undefined): Position | null {
  if (!summary) return null;
  const { latitude, longitude } = summary;
  if (latitude === null || longitude === null) return null;
  if (latitude === 0 && longitude === 0) return null;
  return { lat: latitude, lon: longitude };
}

/** A photo's position on a small map (D249), with the page "Orte" around it and, unless the
 *  place shows it already, the place on OpenStreetMap. */
export function PhotoPosition({
  documentId,
  position,
  openStreetMap = true,
}: {
  documentId: number | null;
  position: Position;
  openStreetMap?: boolean;
}) {
  const { lat, lon } = position;
  return (
    <div className={styles.position}>
      <div className={styles.box}>
        <Suspense fallback={null}>
          <SmallMap lat={lat} lon={lon} />
        </Suspense>
      </div>
      <span className={styles.links}>
        <Link to={photoPlacesHref(documentId, lat, lon)}>Auf der Orte-Seite zeigen</Link>
        {openStreetMap && (
          <a
            href={openStreetMapUrl({ latitude: lat, longitude: lon })}
            target="_blank"
            rel="noopener noreferrer"
          >
            auf OpenStreetMap ansehen
          </a>
        )}
      </span>
    </div>
  );
}
