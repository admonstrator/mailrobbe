import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import {
  useEventPlaces,
  useMapStatus,
  useMapTowns,
  usePhotoDetail,
  usePhotoPoints,
  usePlaceSummary,
  useTextPlaces,
} from "../../api/queries";
import { buttonClass } from "../../components/Button";
import { cx } from "../../lib/cx";
import { listSearch } from "../mails/listState";
import { eventsNotice, photosNotice, textsNotice } from "./labels";
import { MapDataCard } from "./MapDataCard";
import { eventPlaceRadius, textPlaceRadius } from "./mapStyle";
import { PlaceFilters, type LayerInfo } from "./PlaceFilters";
import { PlaceMap, type MapPlace } from "./PlaceMap";
import styles from "./PlacesPage.module.css";
import { EventPlacePanel, PhotoPanel, PlaceOverview, TextPlacePanel } from "./PointPanel";
import {
  areaMailsHref,
  DEFAULT_VIEW,
  parsePlacesState,
  placesSearch,
  roundDegrees,
  samePoint,
  toPlaceParams,
  viewParam,
  type LayerKey,
  type MapView,
  type PlacesState,
  type PointRef,
} from "./urlState";

/** The page "Orte" (D247): the map with the photos, the places named in mails and the places of
 *  invitations, the filters beside it, a point's details on the other side (D248). Filters,
 *  layers, view and point live in the URL. */
export function PlacesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parsePlacesState(searchParams), [searchParams]);
  const params = useMemo(() => toPlaceParams(state), [state]);
  /** A filter, layer or point adds a history entry; the view only replaces the current one. */
  const setState = (next: PlacesState, replace = false) =>
    setSearchParams(placesSearch(next), { replace, preventScrollReset: true });

  const summary = usePlaceSummary();
  const towns = useMapTowns();
  const mapStatus = useMapStatus();
  const photos = usePhotoPoints(params);
  const texts = useTextPlaces(params);
  const events = useEventPlaces(params);
  const [place, setPlace] = useState<MapPlace | null>(null);
  const [focus, setFocus] = useState<MapView | null>(null);
  // The view the map starts with; later moves only write the URL.
  const [initialView] = useState(() => state.view ?? DEFAULT_VIEW);

  const point = state.point;
  const photo = usePhotoDetail(point?.kind === "photo" ? point.id : 0, point?.kind === "photo");
  const textPlace =
    point?.kind === "place"
      ? texts.data?.places.find((one) => one.entity_id === point.id)
      : undefined;
  const eventPlace =
    point?.kind === "event" ? events.data?.places.find((one) => samePoint(one, point)) : undefined;

  // The ring around the point shown on the side, as large as the point's circle.
  const markedLat = photo.data?.latitude ?? textPlace?.lat ?? eventPlace?.lat ?? null;
  const markedLon = photo.data?.longitude ?? textPlace?.lon ?? eventPlace?.lon ?? null;
  const markedRadius = textPlace
    ? textPlaceRadius(texts.data?.places ?? [])(textPlace)
    : eventPlace
      ? eventPlaceRadius(events.data?.places ?? [])(eventPlace)
      : 5.5;
  const showsPoint =
    point !== null && (point.kind !== "photo" || photo.data?.document_id === point.id);
  const marked = useMemo(
    () =>
      showsPoint && markedLat !== null && markedLon !== null
        ? { lat: markedLat, lon: markedLon, radius: markedRadius }
        : null,
    [showsPoint, markedLat, markedLon, markedRadius],
  );

  // Every move of the map writes the URL; the layers switched off stay the same array, so the
  // map's style is not built again for a move.
  const offKey = state.off.join(",");
  const off = useMemo(() => (offKey ? (offKey.split(",") as LayerKey[]) : []), [offKey]);

  const layers: Record<LayerKey, LayerInfo> = {
    photos: {
      count: photos.data?.total,
      notice: photos.data ? photosNotice(photos.data) : null,
      failed: photos.isError,
    },
    texts: {
      count: texts.data?.total,
      notice: texts.data ? textsNotice(texts.data) : null,
      failed: texts.isError,
    },
    events: {
      count: events.data?.total,
      notice: events.data ? eventsNotice(events.data) : null,
      failed: events.isError,
    },
  };

  function onMove(next: MapPlace) {
    setPlace(next);
    const view = {
      lat: roundDegrees(next.view.lat),
      lon: roundDegrees(next.view.lon),
      zoom: next.view.zoom,
    };
    if (viewParam(view) === viewParam(state.view ?? DEFAULT_VIEW)) return;
    setState({ ...state, view }, true);
  }

  function onPick(next: PointRef, at?: MapView) {
    setFocus(at ?? null);
    setState({ ...state, point: next });
  }

  const close = () => setState({ ...state, point: null });
  const ownFilters = Boolean(state.taken_from || state.taken_to || state.device);

  return (
    <div className={styles.page}>
      <title>Orte · Mailrobbe</title>
      <PlaceFilters state={state} onChange={setState} layers={layers} summary={summary.data}>
        <MapDataCard view={place?.bounds ?? null} />
      </PlaceFilters>

      <main className={styles.main}>
        <div className={styles.toolbar}>
          <h1 className={styles.title}>Orte</h1>
          <span className={styles.toolbarNote}>
            {ownFilters &&
              "Aufnahmezeit und Gerät filtern nur die Karte, die Mailliste kennt sie nicht."}
          </span>
          <Link
            to={`/mails?${listSearch(state.list)}`}
            className={buttonClass("default", "sm")}
            title="Die Mails der Filter links, ohne den Kartenausschnitt"
          >
            In der Mailliste öffnen
          </Link>
          {place ? (
            <Link
              to={areaMailsHref(state, place.bounds)}
              className={buttonClass("primary", "sm")}
              title="Die Mails der Filter links, die ein Foto aus diesem Ausschnitt tragen"
            >
              Mails im Kartenausschnitt
            </Link>
          ) : (
            <span
              className={cx(buttonClass("primary", "sm"), styles.disabled)}
              aria-disabled="true"
            >
              Mails im Kartenausschnitt
            </span>
          )}
        </div>
        <div className={styles.map}>
          <PlaceMap
            initialView={initialView}
            towns={towns.data}
            detail={mapStatus.data?.detail_map ?? null}
            photos={photos.data?.points}
            texts={texts.data?.places}
            events={events.data?.places}
            off={off}
            marked={marked}
            focus={focus}
            onMove={onMove}
            onPick={(next) => onPick(next)}
          />
        </div>
      </main>

      <aside className={styles.side} aria-label="Details">
        {point?.kind === "photo" ? (
          <PhotoPanel
            key={point.id}
            id={point.id}
            params={params}
            onPick={onPick}
            onClose={close}
          />
        ) : point?.kind === "place" ? (
          <TextPlacePanel
            id={point.id}
            place={textPlace}
            exact={texts.data?.exact ?? true}
            state={state}
            onClose={close}
          />
        ) : point?.kind === "event" ? (
          <EventPlacePanel place={eventPlace} onClose={close} />
        ) : (
          <PlaceOverview summary={summary.data} />
        )}
      </aside>
    </div>
  );
}
