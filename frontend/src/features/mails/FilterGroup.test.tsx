import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";
import { FilterGroup } from "./FilterGroup";

describe("foldable filter groups", () => {
  it("fold by their heading, remembered in this browser", () => {
    const first = render(
      <FilterGroup id="mails.test" title="Weitere">
        <label>
          <input type="checkbox" /> Mit Anhang
        </label>
      </FilterGroup>,
    );
    const toggle = screen.getByRole("button", { name: "Weitere" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("group", { name: "Weitere" })).toBeTruthy();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByLabelText("Mit Anhang")).toBeNull();
    expect(localStorage.getItem("mailrobbe.filter-groups")).toBe('["mails.test"]');
    first.unmount();

    render(
      <FilterGroup id="mails.test" title="Weitere">
        <label>
          <input type="checkbox" /> Mit Anhang
        </label>
      </FilterGroup>,
    );
    const again = screen.getByRole("button", { name: "Weitere" });
    expect(again.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(again);
    expect(screen.getByLabelText("Mit Anhang")).toBeTruthy();
    expect(localStorage.getItem("mailrobbe.filter-groups")).toBe("[]");
  });

  it("say when a folded group holds a filter", async () => {
    localStorage.setItem("mailrobbe.filter-groups", '["mails.more"]');
    renderApp("/mails?has_attachment=true");
    const toggle = await screen.findByRole("button", { name: /^Weitere/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(toggle.textContent).toBe("Weitere · aktiv");
    expect(screen.queryByRole("checkbox", { name: "Mit Anhang" })).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.textContent).toBe("Weitere");
    expect(screen.getByRole("checkbox", { name: "Mit Anhang" })).toHaveProperty("checked", true);
  });

  it("ignore what the browser keeps when it is not a list", () => {
    localStorage.setItem("mailrobbe.filter-groups", "{oops");
    render(
      <FilterGroup id="mails.date" title="Zeitraum">
        <span>Felder</span>
      </FilterGroup>,
    );
    expect(screen.getByText("Felder")).toBeTruthy();
  });
});
