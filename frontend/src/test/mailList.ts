// Steps of the mail list's tests (D335): its filters are chips that open popovers, its facets
// stand in the panel "Einblicke", its rows are a list.

import { fireEvent, screen, within } from "@testing-library/react";
import { onTestFinished, vi } from "vitest";

/** Opens the filter chip whose name starts with name and returns its popover. */
export async function openFilter(name: string): Promise<HTMLElement> {
  const bar = await screen.findByRole("group", { name: "Filter" });
  const chip = await within(bar).findByRole("button", { name: new RegExp(`^${name}`) });
  if (chip.getAttribute("aria-expanded") !== "true") fireEvent.click(chip);
  return screen.getByRole("dialog", { name });
}

/** Opens the panel "Einblicke" unless it is open, and returns it. */
export async function openInsights(): Promise<HTMLElement> {
  const toggle = await screen.findByRole("button", { name: "Einblicke" });
  if (toggle.getAttribute("aria-pressed") !== "true") fireEvent.click(toggle);
  return screen.getByRole("complementary", { name: "Einblicke" });
}

/** The row of the mail with this subject. */
export function rowOf(subject: string): HTMLElement {
  return screen.getByRole("link", { name: subject }).closest("li")!;
}

/** The rows of the list, once loaded. */
export async function rows(): Promise<HTMLElement[]> {
  const list = await screen.findByRole("list", { name: "Mails" });
  return within(list).getAllByRole("listitem");
}

/** The quiet line of figures under the filters. */
export function figures(): HTMLElement {
  return screen.getByRole("group", { name: "Kennzahlen" });
}

/** Collects the hrefs the menu's downloads click, which jsdom does not follow. */
export function downloads(): string[] {
  const hrefs: string[] = [];
  const spy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    hrefs.push(this.getAttribute("href")!);
  });
  onTestFinished(() => spy.mockRestore());
  return hrefs;
}

/** Chooses an entry of the list's menu "Weitere Aktionen". */
export function menuItem(name: string) {
  fireEvent.click(screen.getAllByRole("button", { name: "Weitere Aktionen" })[0]);
  fireEvent.click(screen.getByRole("menuitem", { name }));
}
