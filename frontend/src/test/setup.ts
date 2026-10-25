import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { fakeMaps } from "./maplibre";

// jsdom has no WebGL: the maps of the page "Orte" and the small maps draw on a stand-in.
vi.mock("../features/places/maplibre", () => import("./maplibre"));

// The welcome note of the first start would sit over every test; one test brings it back.
beforeEach(() => {
  localStorage.setItem("mailrobbe.welcome", "1");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  fakeMaps.reset();
});

// jsdom knows <dialog> but not its methods; the native dialogs need these two.
HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
  this.open = false;
  this.dispatchEvent(new Event("close"));
};
