import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import {
  eventPlaces,
  photoDetail,
  photoPoints,
  photoPointsTruncated,
  placeSummary,
  textPlaces,
  textPlacesSampled,
} from "../../test/fixtures";
import {
  eventsNotice,
  eventStartText,
  formatKm,
  mapErrorText,
  nearestText,
  photosNotice,
  placesStepNotice,
  regionText,
  takenText,
  textsNotice,
} from "./labels";

describe("the texts of a point (D248)", () => {
  it("names the nearest town with distance and direction", () => {
    expect(nearestText(photoDetail.nearest!)).toBe("2,3 km nordöstlich von Weimar");
    expect(regionText(photoDetail.nearest!)).toBe("Thüringen, DE");
    expect(nearestText({ ...photoDetail.nearest!, distance_km: 12.4, direction: "SW" })).toBe(
      "12 km südwestlich von Weimar",
    );
    expect(nearestText({ ...photoDetail.nearest!, distance_km: 0.2, direction: null })).toBe(
      "in Weimar",
    );
    expect(formatKm(0.5)).toBe("0,5 km");
    expect(formatKm(50)).toBe("50 km");
  });

  it("gives the capture time in local time, or as found and marked without zone (D241)", () => {
    expect(takenText(photoDetail)).toBe("14.06.2026 11:12:44");
    expect(takenText({ taken_at: null, taken_text: "2026-10-02T14:31:07" })).toBe(
      "02.10.2026 14:31:07 (ohne Zeitzone)",
    );
    expect(takenText({ taken_at: null, taken_text: "2026:10:02 14:31:07" })).toBe(
      "02.10.2026 14:31:07 (ohne Zeitzone)",
    );
    expect(takenText({ taken_at: null, taken_text: null })).toBe("unbekannt");
  });

  it("gives an event's start with its zone, as written without one, or the day", () => {
    const [hamburg, munich] = eventPlaces.places;
    expect(eventStartText(hamburg.samples[0])).toBe("22.09.2026 15:00");
    expect(eventStartText(hamburg.samples[1])).toBe("10.03.2026 09:00 (ohne Zeitzone)");
    expect(eventStartText(munich.samples[0])).toBe("04.05.2026");
  });
});

describe("what a layer leaves out (D248)", () => {
  it("says when photos are cut at the limit", () => {
    expect(photosNotice(photoPoints)).toBeNull();
    expect(
      photosNotice({ ...photoPointsTruncated, points: photoPoints.points.slice(0, 100) }),
    ).toBe("Gezeigt sind 100 von 23.456 Fotos; Filter grenzen sie ein.");
  });

  it("says when places are cut and counted over a sample (D87)", () => {
    expect(textsNotice(textPlaces)).toBeNull();
    expect(textsNotice(textPlacesSampled)).toBe(
      "Gezeigt sind die 6 Orte mit den meisten Mails von 2.345. Die Mails je Ort sind in einer Stichprobe von 10.000 der passenden Mails gezählt.",
    );
    expect(eventsNotice(eventPlaces)).toBeNull();
    expect(eventsNotice({ ...eventPlaces, total: 2_400 })).toBe(
      "Gezeigt sind die 2 Orte mit den meisten Terminen von 2.400.",
    );
  });

  it("says what the import's step places has still to do", () => {
    expect(placesStepNotice(placeSummary)).toBeNull();
    expect(
      placesStepNotice({ ...placeSummary, texts: { ...placeSummary.texts, waiting: 40 } }),
    ).toBe("40 Orte warten auf den Schritt „Orte bestimmen“ des nächsten Import-Laufs.");
    expect(placesStepNotice({ ...placeSummary, outdated: true })).toMatch(/bestimmt die Orte neu/);
  });
});

describe("the errors of the card Kartendaten", () => {
  const error = (code: string, status = 409) =>
    new ApiError(status, code as never, "English detail");

  it("says them in German", () => {
    expect(mapErrorText(error("map_off"))).toMatch(/abgeschaltet \(MAILROBBE_MAP_SOURCE=off\)/);
    expect(mapErrorText(error("job_running"))).toBe(
      "Es läuft bereits ein Download der Detailkarte.",
    );
    expect(mapErrorText(error("job_running"), "delete")).toBe(
      "Solange ein Download läuft, lässt sich die Detailkarte nicht löschen.",
    );
    expect(mapErrorText(new Error("offline"))).toMatch(/Server ist nicht erreichbar/);
  });
});
