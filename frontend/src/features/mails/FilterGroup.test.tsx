import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { openFilter } from "../../test/mailList";
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

  it("say when a folded group holds a filter", () => {
    localStorage.setItem("mailrobbe.filter-groups", '["mails.more"]');
    render(
      <FilterGroup id="mails.more" title="Weitere" active>
        <label>
          <input type="checkbox" defaultChecked /> Mit Anhang
        </label>
      </FilterGroup>,
    );
    const toggle = screen.getByRole("button", { name: /^Weitere/ });
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

describe("filter chips of the mail list (D335)", () => {
  it("open their group in a popover, which a change leaves open", async () => {
    const { router } = renderApp("/mails");
    const bar = await screen.findByRole("group", { name: "Filter" });
    const chip = within(bar).getByRole("button", { name: "DKIM" });
    expect(chip.getAttribute("aria-haspopup")).toBe("dialog");
    expect(chip.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog", { name: "DKIM" })).toBeNull();

    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    const popover = screen.getByRole("dialog", { name: "DKIM" });
    expect(chip.getAttribute("aria-controls")).toBe(popover.id);
    const box = await within(popover).findByRole("checkbox", { name: /^Ungültig/ });
    fireEvent.click(box);
    const dkim = new URLSearchParams(router.state.location.search).getAll("dkim");
    expect(dkim).toContain("pass");
    expect(dkim).not.toContain("fail");
    expect(screen.getByRole("dialog", { name: "DKIM" })).toBeTruthy();
  });

  it("close by Esc, a click outside and Fertig, giving the focus back", async () => {
    renderApp("/mails");
    const popover = await openFilter("Absender");
    const chip = screen.getByRole("button", { name: "Absender" });
    expect(popover.contains(document.activeElement)).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Absender" })).toBeNull();
    expect(document.activeElement).toBe(chip);

    await openFilter("Absender");
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog", { name: "Absender" })).toBeNull();

    fireEvent.click(within(await openFilter("Absender")).getByRole("button", { name: "Fertig" }));
    expect(screen.queryByRole("dialog", { name: "Absender" })).toBeNull();
    expect(document.activeElement).toBe(chip);
  });

  it("say which chip holds a filter, the rare ones under Weitere Filter", async () => {
    renderApp("/mails?has_attachment=true&dkim=fail");
    const bar = await screen.findByRole("group", { name: "Filter" });
    expect(within(bar).getByRole("button", { name: "DKIM (aktiv)" })).toBeTruthy();
    expect(within(bar).getByRole("button", { name: "Absender" })).toBeTruthy();
    expect(within(bar).getByRole("button", { name: "Weitere Filter (aktiv)" })).toBeTruthy();
    const more = await openFilter("Weitere Filter");
    expect(within(more).getByRole("checkbox", { name: "Mit Anhang" })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(bar).getByRole("button", { name: "Filter entfernen: Mit Anhang" })).toBeTruthy();
  });
});
