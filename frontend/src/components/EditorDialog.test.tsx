import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EDITOR_LIMIT } from "../lib/editor";
import { rows } from "../test/mailList";
import { renderApp } from "../test/render";

function openDialog(button: string): HTMLElement {
  fireEvent.click(screen.getByRole("button", { name: button }));
  return screen.getByRole("dialog", { name: "Name für Notizen und Änderungen" });
}

describe("editor name", () => {
  it("is entered in the top bar, kept in this browser and forgotten when emptied", async () => {
    renderApp("/mails");
    await rows();
    let dialog = openDialog("Namen eintragen");
    expect(
      within(dialog).getByText(
        "Der Name steht an Notizen und Änderungen, wird nur in diesem Browser gespeichert und ist keine Anmeldung.",
      ),
    ).toBeTruthy();
    const field = within(dialog).getByLabelText("Name");
    expect(field.getAttribute("maxlength")).toBe(String(EDITOR_LIMIT));
    fireEvent.change(field, { target: { value: "  Anna   Keller " } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "Bearbeitet als Anna Keller" })).toBeTruthy();
    expect(localStorage.getItem("mailrobbe.editor")).toBe("Anna Keller");

    dialog = openDialog("Bearbeitet als Anna Keller");
    expect(within(dialog).getByLabelText("Name")).toHaveProperty("value", "Anna Keller");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    expect(screen.getByRole("button", { name: "Namen eintragen" })).toBeTruthy();
    expect(localStorage.getItem("mailrobbe.editor")).toBeNull();
  });

  it("keeps the name when the dialog is cancelled", async () => {
    localStorage.setItem("mailrobbe.editor", "Lena");
    renderApp("/mails");
    const dialog = openDialog("Bearbeitet als Lena");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Jan" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    expect(screen.getByRole("button", { name: "Bearbeitet als Lena" })).toBeTruthy();
    expect(localStorage.getItem("mailrobbe.editor")).toBe("Lena");
  });
});
