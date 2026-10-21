import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../test/render";

function searchFor(q: string) {
  const field = screen.getByRole("searchbox", { name: "Suche" });
  fireEvent.change(field, { target: { value: q } });
  fireEvent.submit(field.closest("form")!);
}

describe("the header's search", () => {
  it("keeps the list's search options for a new search, and nothing else (D177)", () => {
    const { router } = renderApp(
      "/mails?q=Neger&dkim=pass&scope=filename&whole_word=true&min_hits=2&cursor=abc&page=2",
    );
    expect(screen.getByRole("searchbox", { name: "Suche" })).toHaveProperty("value", "Neger");
    searchFor("  Jude ");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude&scope=filename&whole_word=true&min_hits=2");
  });

  it("keeps them when the search is emptied", () => {
    const { router } = renderApp("/mails?q=Neger&whole_word=true");
    searchFor("");
    expect(router.state.location.search).toBe("?whole_word=true");
  });

  it("keeps them from a mail opened from the list too", () => {
    const { router } = renderApp("/mails/184221?q=Neger&scope=subject&scope=body");
    searchFor("Jude");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude&scope=subject&scope=body");
  });

  it("starts plain from other screens, and an empty search opens the whole list", () => {
    const { router } = renderApp("/personen?q=anna&scope=subject");
    searchFor("Jude");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude");

    searchFor("");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("");
  });
});
