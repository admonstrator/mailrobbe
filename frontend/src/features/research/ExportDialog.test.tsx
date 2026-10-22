import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ExportInfo } from "../../api/types";
import { exports } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const withPasswords: ExportInfo = { ...exports[0], include_passwords: true };

describe("export with the passwords found (D208)", () => {
  it("leaves them out unless ticked, and says they then stand in plain text", async () => {
    const { calls } = renderApp("/akten/1", (call: ApiCall) =>
      call.url.pathname === "/api/exports" && call.method === "POST"
        ? Response.json(withPasswords, { status: 201 })
        : fixtureApi(call),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Exportieren" }));
    let dialog = screen.getByRole("dialog", { name: "Mails exportieren" });
    const passwords = within(dialog).getByRole("checkbox", {
      name: /Gefundene Kennwörter mitexportieren/,
    });
    expect(passwords).toHaveProperty("checked", false);
    expect(passwords.closest("label")!.textContent).toContain(
      "Die Kennwörter, die Anhänge geöffnet haben, stehen dann mit ihrem Fundort im Klartext im Export.",
    );

    fireEvent.click(passwords);
    fireEvent.click(within(dialog).getByRole("button", { name: "Export anlegen" }));
    dialog = await screen.findByRole("dialog", { name: "Export angelegt" });
    expect(dialog.textContent).toContain(
      "Export 3 „Story Nordstahl“: 24 Mails, ohne Rechercheangaben, mit gefundenen Kennwörtern.",
    );
    const write = calls.find((call) => call.method === "POST")!;
    expect(write.body).toMatchObject({ include_research: false, include_passwords: true });
  });

  it("shows in the list of exports which ones carry them", async () => {
    renderApp("/akten?tab=exporte", (call) =>
      call.url.pathname === "/api/exports"
        ? [{ ...withPasswords, id: 4, label: "Für Kanzlei Weber" }, ...exports]
        : fixtureApi(call),
    );
    const carrying = (await screen.findByText("Export 4", { exact: false })).closest("li")!;
    expect(within(carrying).getByText("mit Kennwörtern")).toBeTruthy();
    const plain = screen.getByText("Story Nordstahl").closest("li")!;
    expect(within(plain).queryByText("mit Kennwörtern")).toBeNull();
  });
});
