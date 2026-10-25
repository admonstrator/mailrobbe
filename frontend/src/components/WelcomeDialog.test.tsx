import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { rows } from "../test/mailList";
import { renderApp } from "../test/render";

describe("welcome note", () => {
  it("shows on the first start with the ways to pay, once per browser", async () => {
    localStorage.removeItem("mailrobbe.welcome");
    renderApp("/mails");
    const dialog = screen.getByRole("dialog", { name: "Willkommen bei Mailrobbe" });
    for (const name of ["GitHub Sponsors", "Buy Me a Coffee", "PayPal", "Ko-fi"]) {
      expect(within(dialog).getByRole("link", { name })).toBeTruthy();
    }
    expect(within(dialog).getByRole("link", { name: "hey@admon.me" })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Verstanden" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(localStorage.getItem("mailrobbe.welcome")).toBe("1");
    await rows();
  });

  it("stays away once seen", async () => {
    renderApp("/mails");
    await rows();
    expect(screen.queryByRole("dialog", { name: "Willkommen bei Mailrobbe" })).toBeNull();
  });
});
