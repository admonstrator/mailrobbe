// A place as a file states it (D167), and the link that shows it on OpenStreetMap. The app
// loads nothing from there; the reader may follow the link (D249).

export interface Coordinates {
  latitude: number;
  longitude: number;
}

/** The place on OpenStreetMap, opened by the reader's choice; the app itself loads no map. */
export function openStreetMapUrl({ latitude, longitude }: Coordinates): string {
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`;
}
