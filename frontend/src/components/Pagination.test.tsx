import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { Pagination, pageWindow, type PaginationProps } from "./Pagination";

const href = (page: number) => `/liste?page=${page}`;

/** Pagination at /liste; router tells where a typed page or a page size went. */
function renderPagination(props: PaginationProps) {
  const element = <Pagination {...props} />;
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: ["/liste"] });
  render(<RouterProvider router={router} />);
  return router;
}

const where = (router: ReturnType<typeof renderPagination>) =>
  `${router.state.location.pathname}${router.state.location.search}`;

describe("pageWindow", () => {
  it("shows the first, the last and the neighbours of the current page, with gaps", () => {
    expect(pageWindow(5, 247)).toEqual([1, null, 4, 5, 6, null, 247]);
    expect(pageWindow(1, 247)).toEqual([1, 2, null, 247]);
    expect(pageWindow(247, 247)).toEqual([1, null, 246, 247]);
    // A gap of one page shows the page.
    expect(pageWindow(4, 9)).toEqual([1, 2, 3, 4, 5, null, 9]);
    expect(pageWindow(1, 1)).toEqual([1]);
    expect(pageWindow(2, 3)).toEqual([1, 2, 3]);
    // Not known: the first and the last page.
    expect(pageWindow(null, 200)).toEqual([1, null, 200]);
  });
});

describe("Pagination", () => {
  it("keeps working with range, Zurück and Weiter alone", () => {
    renderPagination({ range: "51–100 von 230", prev: "/liste", next: "/liste?cursor=c" });
    const nav = screen.getByRole("navigation", { name: "Seiten" });
    expect(nav.textContent).toBe("51–100 von 230‹ ZurückWeiter ›");
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/liste?cursor=c",
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("numbers the pages around the current one as links, the current one marked", () => {
    renderPagination({
      range: "201–250 von 12.345",
      prev: "/liste?cursor=p&page=4",
      next: "/liste?cursor=n&page=6",
      first: href(1),
      last: href(247),
      numbers: { current: 5, pages: 247, more: false, href },
    });
    const nav = screen.getByRole("navigation", { name: "Seiten" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "« Erste Seite",
      "‹ Zurück",
      "1",
      "4",
      "5",
      "6",
      "247",
      "Weiter ›",
      "Letzte Seite »",
    ]);
    expect(nav.textContent).toContain("1…456…247");
    const current = screen.getByRole("link", { name: "Seite 5" });
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(current.getAttribute("href")).toBe("/liste?page=5");
    expect(screen.getByRole("link", { name: "Seite 4" }).getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "Letzte Seite »" }).getAttribute("href")).toBe(
      "/liste?page=247",
    );
  });

  it("shows first and last page as steps without a link where the list is on them", () => {
    renderPagination({
      range: "1–50 von 70",
      prev: null,
      next: "/liste?cursor=n&page=2",
      first: null,
      last: href(2),
      numbers: { current: 1, pages: 2, more: false, href },
    });
    expect(screen.queryByRole("link", { name: "« Erste Seite" })).toBeNull();
    const steps = screen.getByRole("navigation", { name: "Seiten" }).querySelectorAll("span");
    const disabled = [...steps].filter((step) => step.getAttribute("aria-disabled") === "true");
    expect(disabled.map((step) => step.textContent)).toEqual(["« Erste Seite", "‹ Zurück"]);
    expect(screen.getByRole("link", { name: "Letzte Seite »" })).toBeTruthy();
  });

  it("ends the numbers with a gap where the list goes on after them", () => {
    renderPagination({
      range: "die letzten 50 von mehr als 10.000",
      prev: "/liste?cursor=p",
      next: null,
      first: href(1),
      last: null,
      numbers: { current: null, pages: 200, more: true, href },
    });
    const nav = screen.getByRole("navigation", { name: "Seiten" });
    expect(nav.textContent).toContain("1…200…");
    expect(within(nav).queryByRole("link", { current: "page" })).toBeNull();
  });

  it("jumps to the page typed, by Enter or the button, at most the last one", () => {
    const router = renderPagination({
      range: "1–50 von 12.345",
      prev: null,
      next: "/liste?cursor=n&page=2",
      numbers: { current: 1, pages: 247, more: false, href },
    });
    const field = screen.getByRole("spinbutton", { name: "Seite" });
    fireEvent.change(field, { target: { value: "17" } });
    fireEvent.submit(field.closest("form")!);
    expect(where(router)).toBe("/liste?page=17");

    fireEvent.change(screen.getByRole("spinbutton", { name: "Seite" }), {
      target: { value: "999" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Los" }));
    expect(where(router)).toBe("/liste?page=247");

    // Nothing usable typed: nowhere.
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seite" }), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Los" }));
    expect(where(router)).toBe("/liste?page=247");
  });

  it("lets a list that goes on take any page typed", () => {
    const router = renderPagination({
      range: "1–50 von mehr als 10.000",
      prev: null,
      next: "/liste?cursor=n&page=2",
      numbers: { current: 1, pages: 200, more: true, href },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Seite" }), {
      target: { value: "350" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Los" }));
    expect(where(router)).toBe("/liste?page=350");
  });

  it("chooses the page size among 25, 50, 100 and 200", () => {
    const router = renderPagination({
      range: "1–50 von 230",
      prev: null,
      next: "/liste?cursor=n",
      size: { limit: 50, href: (limit) => `/liste?limit=${limit}` },
    });
    const size = screen.getByRole("combobox", { name: "Pro Seite" });
    expect(
      within(size)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["25", "50", "100", "200"]);
    expect((size as HTMLSelectElement).value).toBe("50");
    fireEvent.change(size, { target: { value: "100" } });
    expect(where(router)).toBe("/liste?limit=100");
  });
});
