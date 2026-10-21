import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp, type ApiCall } from "../../test/render";

const listCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/dkim/selectors");

function row(name: string): HTMLElement {
  return screen.getByRole("link", { name }).closest("tr")!;
}

const cells = (name: string) =>
  within(row(name))
    .getAllByRole("cell")
    .map((cell) => cell.textContent);

describe("selector list", () => {
  it("lists the open names, most mails first, with their figures", async () => {
    const { calls } = renderApp("/import/selektoren");
    const first = await screen.findByRole("link", { name: "mx1._domainkey.archiv-1.example" });
    expect(first.getAttribute("href")).toBe("/import/selektoren/mx1._domainkey.archiv-1.example");
    expect(document.title).toBe("Gelöschte Selektoren · Mailrobbe");
    expect(screen.getByRole("heading", { level: 1, name: "Gelöschte Selektoren" })).toBeTruthy();
    expect(screen.getByText("56 Selektoren")).toBeTruthy();
    expect(listCalls(calls)[0].url.search).toBe("");
    // The import stays the active screen in the navigation.
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    expect(within(navigation).getByRole("link", { name: "Import" }).className).toMatch(/active/);

    expect(cells("mx1._domainkey.archiv-1.example")).toEqual([
      "mx1archiv-1.example",
      "300",
      "300",
      "300",
      "300",
      "02.04.2016 – 20.11.2018",
      "–",
      "nicht im DNS",
    ]);
    expect(
      within(row("mx1._domainkey.archiv-1.example"))
        .getByRole("img", { name: "Schlüssel nicht abrufbar" })
        .getAttribute("title"),
    ).toBe("Schlüssel nicht abrufbar");
    expect(screen.queryByRole("link", { name: "k1._domainkey.verein-nord.example" })).toBeNull();

    expect(screen.getByText("1–50 von 56")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/import/selektoren?page=2",
    );
  });

  it("keeps the filter and the page in the URL and asks with offsets", async () => {
    const { router, calls } = renderApp("/import/selektoren?page=2");
    expect(
      await screen.findByRole("link", { name: "k1._domainkey.verein-nord.example" }),
    ).toBeTruthy();
    expect(listCalls(calls)[0].url.search).toBe("?offset=50");
    expect(cells("k1._domainkey.verein-nord.example").slice(4)).toEqual([
      "1",
      "01.06.2017",
      "–",
      "nicht abgefragt",
    ]);
    expect(cells("google._domainkey.stadtwerke-beispiel.example").at(-1)).toBe("Schlüssel im DNS");
    expect(
      within(row("google._domainkey.stadtwerke-beispiel.example")).getByRole("img", {
        name: "DKIM ungültig",
      }),
    ).toBeTruthy();
    expect(screen.getByText("51–56 von 56")).toBeTruthy();
    expect(screen.getByRole("link", { name: "‹ Zurück" }).getAttribute("href")).toBe(
      "/import/selektoren",
    );

    fireEvent.click(screen.getByRole("button", { name: "geklärt" }));
    expect(router.state.location.search).toBe("?show=resolved");
    expect(
      await screen.findByRole("link", { name: "s2019._domainkey.nordlicht-gmbh.example" }),
    ).toBeTruthy();
    expect(listCalls(calls).at(-1)!.url.search).toBe("?show=resolved");
    expect(screen.getByRole("button", { name: "geklärt" }).getAttribute("aria-pressed")).toBe(
      "true",
    );
    const resolved = cells("s2019._domainkey.nordlicht-gmbh.example");
    expect(resolved.slice(1, 3)).toEqual(["415", "415"]);
    expect(resolved[3]).toBe("4123");
    expect(resolved.slice(5)).toEqual(["11.02.2019 – 30.12.2020", "2dokumentiert", "nicht im DNS"]);
    expect(screen.getByText("1–1 von 1")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "alle" }));
    expect(router.state.location.search).toBe("?show=all");
    await waitFor(() => expect(screen.getByText("1–50 von 57")).toBeTruthy());
  });

  it("searches names as typed and says when none fits", async () => {
    const { router, calls } = renderApp("/import/selektoren");
    await screen.findByRole("link", { name: "mx1._domainkey.archiv-1.example" });
    const field = screen.getByRole("searchbox", { name: "Selektor suchen" });

    fireEvent.change(field, { target: { value: " verein " } });
    await waitFor(() => expect(router.state.location.search).toBe("?q=verein"));
    expect(router.state.historyAction).toBe("REPLACE");
    expect(
      await screen.findByRole("link", { name: "k1._domainkey.verein-nord.example" }),
    ).toBeTruthy();
    expect(listCalls(calls).at(-1)!.url.search).toBe("?q=verein");
    expect(screen.getByText("1 Selektor gefunden")).toBeTruthy();

    fireEvent.change(field, { target: { value: "nirgendwo" } });
    expect(await screen.findByText("Kein Selektor gefunden")).toBeTruthy();
    expect(screen.getByText("Kein Schlüsselname enthält „nirgendwo“.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Suche leeren" }).getAttribute("href")).toBe(
      "/import/selektoren",
    );
  });

  it("opens a name's page from its row", async () => {
    const { router } = renderApp("/import/selektoren?show=resolved");
    const link = await screen.findByRole("link", {
      name: "s2019._domainkey.nordlicht-gmbh.example",
    });
    fireEvent.click(link.closest("tr")!.querySelector("td:nth-child(3)")!);
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(
        "/import/selektoren/s2019._domainkey.nordlicht-gmbh.example",
      ),
    );
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "s2019._domainkey.nordlicht-gmbh.example",
      }),
    ).toBeTruthy();
  });
});
