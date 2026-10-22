import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { fakeMaps } from "./maplibre";

// jsdom has no WebGL: the maps of the page "Orte" and the small maps draw on a stand-in.
vi.mock("../features/places/maplibre", () => import("./maplibre"));

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
