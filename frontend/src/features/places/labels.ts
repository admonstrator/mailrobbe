// German texts of the page "Orte" (D247, D248) and the card "Kartendaten" (D245, D246).

import { ApiError } from "../../api/client";
import {
  FACET_MAILS,
  type CompassDirection,
  type EventPlaces,
  type MapDetailKey,
  type MapRegionKey,
  type NearestTown,
  type PhotoPoints,
  type PlaceEvent,
  type PlaceSummary,
  type TextPlaces,
} from "../../api/types";
import { formatDateTime, formatDay, formatNumber } from "../../lib/format";
import type { LayerKey } from "./urlState";

export const LAYER_LABELS: Record<LayerKey, string> = {
  photos: "Fotos",
  texts: "Orte aus Texten",
  events: "Termine",
};

/** What each layer draws, as the switch's title says it. */
export const LAYER_HINTS: Record<LayerKey, string> = {
  photos: "Fotos nach der GPS-Position in ihren EXIF-Daten; herausgezoomt zu Zahlen gebündelt",
  texts: "Orte, die Mails oder ihre Anhänge nennen; je größer der Kreis, desto mehr Mails",
  events: "Orte von Kalendereinladungen, nach dem Ort, der in der Einladung steht",
};

export const REGION_LABELS: Record<MapRegionKey, string> = {
  de: "Deutschland",
  at: "Österreich",
  ch: "Schweiz",
  dach: "DACH",
  view: "Aktueller Kartenausschnitt",
};

export const DETAIL_LABELS: Record<MapDetailKey, string> = {
  overview: "Überblick",
  streets: "Straßen",
  full: "Alle Details",
};

export const DETAIL_HINTS: Record<MapDetailKey, string> = {
  overview: "Orte, Hauptstraßen, Flüsse und Wälder",
  streets: "jede Straße",
  full: "jede Straße, Gebäude und Orte von Interesse",
};

const DIRECTION_TEXTS: Record<CompassDirection, string> = {
  N: "nördlich",
  NO: "nordöstlich",
  O: "östlich",
  SO: "südöstlich",
  S: "südlich",
  SW: "südwestlich",
  W: "westlich",
  NW: "nordwestlich",
};

const kmFormat = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

/** "2,3 km", "12 km": tenths below 10 km. */
export function formatKm(km: number): string {
  return `${km < 10 ? kmFormat.format(km) : formatNumber(Math.round(km))} km`;
}

/** "2,3 km nordöstlich von Weimar", "in Weimar" within half a kilometre of it. */
export function nearestText(nearest: NearestTown): string {
  if (nearest.direction === null) return `in ${nearest.name}`;
  return `${formatKm(nearest.distance_km)} ${DIRECTION_TEXTS[nearest.direction]} von ${nearest.name}`;
}

/** "Thüringen, DE" after the town. */
export function regionText(nearest: NearestTown): string {
  return [nearest.region, nearest.country].filter(Boolean).join(", ");
}

/** Coordinates as the panels show them: "50,98012, 11,32903". */
export function coordinatesText(lat: number, lon: number): string {
  const format = (value: number) => value.toLocaleString("de-DE", { maximumFractionDigits: 5 });
  return `${format(lat)}, ${format(lon)}`;
}

/** When a photo was taken (D241): in local time when its zone is known, else as the file gives
 *  it, marked as without zone. */
export function takenText(photo: { taken_at: string | null; taken_text: string | null }): string {
  if (photo.taken_at) return formatDateTime(photo.taken_at, true);
  if (!photo.taken_text) return "unbekannt";
  const iso = /^(\d{4})[-:](\d{2})[-:](\d{2})[T ](\d{2}:\d{2}(:\d{2})?)/.exec(photo.taken_text);
  const shown = iso ? `${iso[3]}.${iso[2]}.${iso[1]} ${iso[4]}` : photo.taken_text;
  return `${shown} (ohne Zeitzone)`;
}

/** "3 Fotos", "1 Foto"; the other nouns of the page alike. */
export function countText(count: number, one: string, many: string): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`;
}

/** When an invitation's event starts: with its zone in local time, else as written. */
export function eventStartText(event: PlaceEvent): string | null {
  if (event.all_day && event.starts_local) return formatDay(event.starts_local.slice(0, 10));
  if (event.starts_at) return formatDateTime(event.starts_at);
  if (event.starts_local) {
    const [day, time] = event.starts_local.split("T");
    return `${[formatDay(day), time?.slice(0, 5)].filter(Boolean).join(" ")} (ohne Zeitzone)`;
  }
  return null;
}

/** What the photos' layer leaves out: the photos beyond PHOTO_POINT_LIMIT (D248). */
export function photosNotice(photos: PhotoPoints): string | null {
  if (!photos.truncated) return null;
  return `Gezeigt sind ${formatNumber(photos.points.length)} von ${formatNumber(photos.total)} Fotos; Filter grenzen sie ein.`;
}

/** What the layer of places from texts leaves out: the places beyond TEXT_PLACE_LIMIT, and its
 *  mails counted over a sample of the matching ones (D87). */
export function textsNotice(texts: TextPlaces): string | null {
  const parts: string[] = [];
  if (texts.total > texts.places.length) {
    parts.push(
      `Gezeigt sind die ${formatNumber(texts.places.length)} Orte mit den meisten Mails von ${formatNumber(texts.total)}.`,
    );
  }
  if (!texts.exact) {
    parts.push(
      `Die Mails je Ort sind in einer Stichprobe von ${formatNumber(FACET_MAILS)} der passenden Mails gezählt.`,
    );
  }
  return parts.length ? parts.join(" ") : null;
}

export function eventsNotice(events: EventPlaces): string | null {
  if (events.total <= events.places.length) return null;
  return `Gezeigt sind die ${formatNumber(events.places.length)} Orte mit den meisten Terminen von ${formatNumber(events.total)}.`;
}

/** What the import's step places has still to do or do again (D242, D243). */
export function placesStepNotice(summary: PlaceSummary): string | null {
  const waiting = summary.texts.waiting + summary.events.waiting;
  if (summary.outdated) {
    return "Die Ortslisten oder ihre Regeln haben sich geändert: Der nächste Import-Lauf bestimmt die Orte neu.";
  }
  if (waiting > 0) {
    return `${countText(waiting, "Ort wartet", "Orte warten")} auf den Schritt „Orte bestimmen“ des nächsten Import-Laufs.`;
  }
  return null;
}

/** The notice for an action of the card "Kartendaten" the API refused or that failed. */
export function mapErrorText(error: Error, action: "start" | "stop" | "delete" = "start"): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "map_off":
        return "Der Download von Kartendaten ist auf diesem Server abgeschaltet (MAILROBBE_MAP_SOURCE=off).";
      case "job_running":
        return action === "delete"
          ? "Solange ein Download läuft, lässt sich die Detailkarte nicht löschen."
          : "Es läuft bereits ein Download der Detailkarte.";
      case "no_job":
        return "Es läuft gerade kein Download, der angehalten werden könnte.";
      case "invalid_option":
        return `Diese Auswahl lässt sich nicht laden (${error.message}).`;
    }
    if (error.status === 422) return "Diese Auswahl lässt sich nicht laden.";
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
