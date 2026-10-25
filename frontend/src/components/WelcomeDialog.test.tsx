import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { rows } from "../test/mailList";
import { renderApp } from "../test/render";

const TITLE = "Frei nutzbar. Den Preis bestimmst du.";

describe("welcome note", () => {
  it("shows on the first start with the suggestions and the ways to pay, once per browser", async () => {
    localStorage.removeItem("mailrobbe.welcome");
    renderApp("/mails");
    const dialog = screen.getByRole("dialog", { name: TITLE });
    expect(within(dialog).getByText("Wie viele Energydrinks ist es dir wert?")).toBeTruthy();
    for (const cans of ["3 Dosen", "33 Dosen", "200 Dosen"]) {
      expect(within(dialog).getByText(cans)).toBeTruthy();
    }
    for (const name of ["GitHub Sponsors", "Buy Me a Coffee", "PayPal", "Ko-fi"]) {
      expect(within(dialog).getByRole("link", { name })).toBeTruthy();
    }
    expect(within(dialog).getByRole("link", { name: "hey@admon.me" })).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Los geht’s" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(localStorage.getItem("mailrobbe.welcome")).toBe("1");
    await rows();
  });

  it("comes back on the next start when put off", async () => {
    localStorage.removeItem("mailrobbe.welcome");
    renderApp("/mails");
    const dialog = screen.getByRole("dialog", { name: TITLE });
    fireEvent.click(within(dialog).getByRole("button", { name: "Später erinnern" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(localStorage.getItem("mailrobbe.welcome")).toBeNull();
    await rows();
  });

  it("stays away once seen", async () => {
    renderApp("/mails");
    await rows();
    expect(screen.queryByRole("dialog", { name: TITLE })).toBeNull();
  });
});
