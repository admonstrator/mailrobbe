import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SettingInfo, SettingsView } from "../../api/types";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { MIB } from "./model";

function setting(name: string, fields: Partial<SettingInfo>): SettingInfo {
  return {
    name,
    kind: "text",
    value: "",
    base: "",
    source: "default",
    secret_set: false,
    choices: [],
    minimum: null,
    maximum: null,
    changed_at: null,
    changed_by: null,
    ...fields,
  };
}

const view: SettingsView = {
  items: [
    setting("internal_domains", {}),
    setting("timezone", { value: "Europe/Berlin", base: "Europe/Berlin", source: "env" }),
    setting("block_min_mails", {
      kind: "integer",
      value: 7,
      base: 25,
      source: "stored",
      minimum: 2,
      changed_at: "2026-10-23T08:30:00Z",
      changed_by: "Aaron",
    }),
    setting("ai_text_key", { kind: "secret", value: null, base: null }),
    setting("ai_text_protocol", {
      kind: "choice",
      value: "auto",
      base: "auto",
      choices: ["auto", "openai", "ollama"],
    }),
    setting("import_max_mail_size", { kind: "bytes", value: 128 * MIB, base: 128 * MIB }),
    setting("dkim_offline", { kind: "boolean", value: false, base: false }),
    setting("future_option", { value: "x", base: "x" }),
  ],
  fixed: ["database_url"],
};

function api(answer?: (call: ApiCall) => unknown) {
  return (call: ApiCall): unknown => {
    if (call.url.pathname !== "/api/settings") return fixtureApi(call);
    if (call.method === "PUT" && answer) return answer(call);
    return view;
  };
}

const puts = (calls: ApiCall[]) =>
  calls.filter((call) => call.method === "PUT" && call.url.pathname === "/api/settings");

/** Chooses a group in the navigation at the left. */
function open(title: string) {
  const groups = screen.getByRole("navigation", { name: "Bereiche der Einstellungen" });
  fireEvent.click(within(groups).getByRole("button", { name: title }));
  expect(screen.getByRole("heading", { level: 2, name: title })).toBeTruthy();
}

describe("settings page", () => {
  it("shows every setting in its group with where its value comes from", async () => {
    renderApp("/einstellungen", api());
    expect(await screen.findByLabelText("Eigene Domains")).toHaveProperty("value", "");
    expect(screen.getByRole("heading", { name: "Einstellungen", level: 1 })).toBeTruthy();
    const zone = screen.getByLabelText("Zeitzone");
    expect(zone).toHaveProperty("value", "Europe/Berlin");
    expect(screen.getAllByText("aus .env")).toHaveLength(1);
    expect(screen.getByLabelText("Standardblock ab")).toHaveProperty("value", "7");
    expect(screen.getByText(/Hier geändert von Aaron am 23\.10\.2026/).textContent).toContain(
      "sonst 25.",
    );
    expect(screen.getByRole("button", { name: "Archiv und Signale" })).toBeTruthy();
    open("KI: Textmodell");
    expect(screen.getByLabelText("API-Schlüssel").getAttribute("placeholder")).toBe("keiner");
    expect(screen.getByRole("option", { name: "OpenAI-kompatibel" })).toBeTruthy();
    open("Import");
    expect(screen.getByLabelText("Mails vollständig bis")).toHaveProperty("value", "128");
    open("Weitere");
    expect(screen.getByLabelText("future_option")).toHaveProperty("value", "x");
    expect(screen.queryByRole("region", { name: "Änderungen" })).toBeNull();
  });

  it("saves the changed fields at once, a reset as null and an empty key not at all", async () => {
    const { calls } = renderApp(
      "/einstellungen",
      api(() => view),
    );
    fireEvent.change(await screen.findByLabelText("Zeitzone"), {
      target: { value: "Europe/Vienna" },
    });
    fireEvent.change(screen.getByLabelText("Eigene Domains"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zurücksetzen" }));
    expect(screen.getByLabelText("Standardblock ab")).toHaveProperty("value", "25");
    expect(screen.getByText("Wird beim Speichern zurückgesetzt.")).toBeTruthy();
    open("KI: Textmodell");
    fireEvent.change(screen.getByLabelText("API-Schlüssel"), { target: { value: "sk-1" } });
    open("Import");
    fireEvent.change(screen.getByLabelText("Mails vollständig bis"), { target: { value: "64" } });
    open("DKIM");
    fireEvent.click(screen.getByLabelText("Ohne DNS prüfen"));
    const bar = screen.getByRole("region", { name: "Änderungen" });
    expect(within(bar).getByRole("status").textContent).toBe("5 Änderungen");
    fireEvent.click(within(bar).getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(puts(calls)).toHaveLength(1));
    expect(puts(calls)[0].body).toEqual({
      values: {
        timezone: "Europe/Vienna",
        block_min_mails: null,
        ai_text_key: "sk-1",
        import_max_mail_size: 64 * MIB,
        dkim_offline: true,
      },
    });
    expect(await within(bar).findByText("Gespeichert.")).toBeTruthy();
    open("Archiv und Signale");
    expect(screen.getByLabelText("Zeitzone")).toHaveProperty("value", "Europe/Berlin");
  });

  it("does not save a number field that holds no number", async () => {
    const { calls } = renderApp("/einstellungen", api());
    fireEvent.change(await screen.findByLabelText("Standardblock ab"), { target: { value: "" } });
    const bar = screen.getByRole("region", { name: "Änderungen" });
    expect(within(bar).getByRole("status").textContent).toBe("Keine Zahl: „Standardblock ab“");
    expect(within(bar).getByRole("button", { name: "Speichern" })).toHaveProperty("disabled", true);
    fireEvent.click(within(bar).getByRole("button", { name: "Verwerfen" }));
    expect(screen.getByLabelText("Standardblock ab")).toHaveProperty("value", "7");
    expect(puts(calls)).toHaveLength(0);
  });

  it("names the setting the server did not take", async () => {
    renderApp(
      "/einstellungen",
      api(() =>
        Response.json(
          {
            detail: {
              code: "invalid_setting",
              message: "timezone: PostgreSQL does not know it",
            },
          },
          { status: 400 },
        ),
      ),
    );
    fireEvent.change(await screen.findByLabelText("Zeitzone"), { target: { value: "Mars/Olymp" } });
    fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
    expect(
      await screen.findByText("Nicht gespeichert: „Zeitzone“ nimmt diesen Wert nicht an."),
    ).toBeTruthy();
    expect(screen.getByText("Nicht angenommen: PostgreSQL does not know it")).toBeTruthy();
    expect(screen.getByLabelText("Zeitzone")).toHaveProperty("value", "Mars/Olymp");
  });

  it("is in the sidebar's group System", () => {
    const { router } = renderApp("/einstellungen", api());
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const settings = within(navigation).getByRole("link", { name: "Einstellungen" });
    expect(settings.getAttribute("aria-current")).toBe("page");
    fireEvent.click(within(navigation).getByRole("link", { name: "KI" }));
    expect(router.state.location.pathname).toBe("/ki");
    fireEvent.click(within(navigation).getByRole("link", { name: "Einstellungen" }));
    expect(router.state.location.pathname).toBe("/einstellungen");
  });
});
