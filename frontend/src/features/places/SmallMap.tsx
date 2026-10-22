import { useMemo, useRef } from "react";

import { useMapStatus, useMapTowns } from "../../api/queries";
import type { DetailMap, TownLabel } from "../../api/types";
import { mapStyle } from "./mapStyle";
import styles from "./SmallMap.module.css";
import { useMap } from "./useMap";

/** The zoom of a small map: the streets around the point where the detail map covers it, the
 *  towns around it on the overview. */
export function smallMapZoom(detail: DetailMap | null, lat: number, lon: number): number {
  if (!detail) return 7;
  const [west, south, east, north] = detail.bbox;
  const inside = lon >= west && lon <= east && lat >= south && lat <= north;
  return inside ? Math.min(14, detail.max_zoom + 1) : 7;
}

/** A photo's position on a small map that does not move (D249): the overview, the detail map
 *  where there is one, the photo marked. It waits for the map status, which decides the zoom. */
export function SmallMap({ lat, lon }: { lat: number; lon: number }) {
  const status = useMapStatus(false);
  const towns = useMapTowns();
  if (status.isPending) return null;
  return (
    <Drawn
      // Another photo is another map: its centre and zoom are the map's first options.
      key={`${lat},${lon}`}
      lat={lat}
      lon={lon}
      detail={status.data?.detail_map ?? null}
      towns={towns.data}
    />
  );
}

function Drawn({
  lat,
  lon,
  detail,
  towns,
}: {
  lat: number;
  lon: number;
  detail: DetailMap | null;
  towns: TownLabel[] | undefined;
}) {
  const container = useRef<HTMLDivElement>(null);
  const style = useMemo(
    () =>
      mapStyle({
        origin: window.location.origin,
        towns,
        detail,
        photos: [{ id: 0, lat, lon }],
        marked: { lat, lon, radius: 5.5 },
      }),
    [towns, detail, lat, lon],
  );
  const { failed } = useMap(container, style, {
    center: [lon, lat],
    zoom: smallMapZoom(detail, lat, lon),
    interactive: false,
    attributionControl: { compact: true },
  });
  if (failed) {
    return <p className={styles.failed}>Die Karte braucht WebGL, das in diesem Browser fehlt.</p>;
  }
  return (
    <div
      ref={container}
      className={styles.map}
      role="img"
      aria-label="Kleine Karte mit dem Aufnahmeort"
    />
  );
}
