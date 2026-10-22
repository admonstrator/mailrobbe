import type { GeoJSONSource } from "maplibre-gl";
import { useEffect, useEffectEvent, useMemo, useRef } from "react";

import type {
  BBox,
  DetailMap,
  EventPlace,
  PhotoPoint,
  TextPlace,
  TownLabel,
} from "../../api/types";
import { ErrorState } from "../../components/ErrorState";
import { CLICK_LAYERS, mapStyle } from "./mapStyle";
import styles from "./PlaceMap.module.css";
import { useMap } from "./useMap";
import { MAX_MAP_ZOOM, type LayerKey, type MapView, type PointRef } from "./urlState";

/** Where the map is: its centre and zoom (the URL keeps them) and the area it shows. */
export interface MapPlace {
  view: MapView;
  bounds: BBox;
}

export interface PlaceMapProps {
  initialView: MapView;
  towns: TownLabel[] | undefined;
  detail: DetailMap | null;
  photos: PhotoPoint[] | undefined;
  texts: TextPlace[] | undefined;
  events: EventPlace[] | undefined;
  off: readonly LayerKey[];
  /** The point the side shows, ringed on the map. */
  marked: { lat: number; lon: number; radius: number } | null;
  /** A point to bring into view, at this zoom at least. */
  focus: MapView | null;
  onMove: (place: MapPlace) => void;
  onPick: (point: PointRef) => void;
}

/** The map of the page "Orte" (D247): the overview with the detail map where there is one, the
 *  three layers on it. A click on a bundle of photos zooms in, on a point picks it. */
export function PlaceMap({
  initialView,
  towns,
  detail,
  photos,
  texts,
  events,
  off,
  marked,
  focus,
  onMove,
  onPick,
}: PlaceMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const style = useMemo(
    () =>
      mapStyle({
        origin: window.location.origin,
        towns,
        detail,
        photos,
        texts,
        events,
        off,
        marked,
      }),
    [towns, detail, photos, texts, events, off, marked],
  );
  const { map, failed } = useMap(
    container,
    style,
    {
      center: [initialView.lon, initialView.lat],
      zoom: initialView.zoom,
      maxZoom: MAX_MAP_ZOOM,
    },
    true,
  );

  const moved = useEffectEvent(() => {
    if (!map) return;
    const center = map.getCenter();
    const bounds = map.getBounds();
    onMove({
      view: { lat: center.lat, lon: center.lng, zoom: map.getZoom() },
      bounds: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
    });
  });

  const clicked = useEffectEvent((point: { x: number; y: number }) => {
    if (!map) return;
    const [feature] = map.queryRenderedFeatures([point.x, point.y], { layers: CLICK_LAYERS });
    if (!feature) return;
    const properties = feature.properties ?? {};
    if (feature.layer.id === "photos-cluster" && feature.geometry.type === "Point") {
      const [lon, lat] = feature.geometry.coordinates;
      void map
        .getSource<GeoJSONSource>("photos")
        ?.getClusterExpansionZoom(Number(properties.cluster_id))
        .then((zoom) => map.easeTo({ center: [lon, lat], zoom }));
    } else if (feature.layer.id === "photos-point") {
      onPick({ kind: "photo", id: Number(properties.id) });
    } else if (feature.layer.id === "texts-circle") {
      onPick({ kind: "place", id: Number(properties.id) });
    } else if (feature.layer.id === "events-circle") {
      onPick({ kind: "event", lat: Number(properties.lat), lon: Number(properties.lon) });
    }
  });

  const hovered = useEffectEvent((point: { x: number; y: number }) => {
    if (!map) return;
    const over = map.queryRenderedFeatures([point.x, point.y], { layers: CLICK_LAYERS });
    map.getCanvas().style.cursor = over.length ? "pointer" : "";
  });

  useEffect(() => {
    if (!map) return;
    const onMoveEnd = () => moved();
    const onClick = (event: { point: { x: number; y: number } }) => clicked(event.point);
    const onMouseMove = (event: { point: { x: number; y: number } }) => hovered(event.point);
    map.on("moveend", onMoveEnd);
    map.on("click", onClick);
    map.on("mousemove", onMouseMove);
    moved();
    return () => {
      map.off("moveend", onMoveEnd);
      map.off("click", onClick);
      map.off("mousemove", onMouseMove);
    };
  }, [map]);

  useEffect(() => {
    if (!map || !focus) return;
    const bounds = map.getBounds();
    const inside = bounds.contains([focus.lon, focus.lat]);
    if (inside && map.getZoom() >= focus.zoom) return;
    map.easeTo({ center: [focus.lon, focus.lat], zoom: Math.max(map.getZoom(), focus.zoom) });
  }, [map, focus]);

  if (failed) {
    return (
      <ErrorState title="Die Karte lässt sich in diesem Browser nicht zeichnen.">
        Sie braucht WebGL, das hier fehlt oder abgeschaltet ist.
      </ErrorState>
    );
  }
  return <div ref={container} className={styles.map} role="region" aria-label="Karte" />;
}
