import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Graph } from "../../api/types";
import { graph as graphFixture } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

// Cytoscape needs a real canvas; the page is tested with a stand-in that lists the nodes as
// buttons, which select them the way a click on the map does.
vi.mock("./GraphCanvas", () => ({
  GraphCanvas: ({ graph, onSelect }: { graph?: Graph; onSelect: (id: number | null) => void }) => (
    <div data-testid="graph-canvas">
      {graph?.nodes.map((node) => (
        <button key={node.id} type="button" onClick={() => onSelect(node.id)}>
          Knoten {node.id}
        </button>
      ))}
    </div>
  ),
}));

afterEach(() => {
  vi.useRealTimers();
});

const graphCalls = (calls: ApiCall[]) => calls.filter((call) => call.url.pathname === "/api/graph");
const sizeCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/graph/size");
const query = (call: ApiCall) => [...call.url.searchParams].map(([k, v]) => `${k}=${v}`).join("&");
const search = (router: { state: { location: { search: string } } }) =>
  decodeURIComponent(router.state.location.search);

function failWith(path: string, status: number, code: string, message = "") {
  return (call: ApiCall) =>
    call.url.pathname === path
      ? Response.json({ detail: { code, message } }, { status })
      : fixtureApi(call);
}

describe("map page", () => {
  it("shows the top 50 by default with figures, legend and edge table", async () => {
    const { calls } = renderApp("/karte");
    expect(await screen.findByText("Knoten 11")).toBeTruthy();
    expect(query(graphCalls(calls)[0])).toBe("mode=top&hide_lists=true");
    expect(document.title).toBe("Beziehungskarte · Mailrobbe");

    const header = screen.getByText("Mails im Ausschnitt", { exact: false });
    expect(header.textContent).toBe("9 Knoten · 12 Kanten · 1.472 Mails im Ausschnitt");
    const legend = screen.getByRole("list", { name: "Domainfarben" });
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "nordlicht-gmbh.example",
      "stadtwerke-beispiel.example",
      "kanzlei-muster.example",
      "mail.example",
      "post.example",
    ]);
    expect(
      screen.getByText("Kantentabelle: 34.912 Paare · letzte Aggregation 21.10.2026 03:20"),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "GraphML / Gephi" }).getAttribute("href")).toBe(
      "/api/graph/export.graphml?mode=top&hide_lists=true",
    );
    expect(screen.getByRole("radio", { name: /Top-N/ })).toHaveProperty("checked", true);
    expect(await screen.findByText("Ergibt 9 Knoten, 12 Kanten.")).toBeTruthy();
  });

  it("opens the mail detail's link as an ego network with named centers", async () => {
    const { calls } = renderApp("/karte?center=11,12,15,13&depth=2");
    await screen.findByText("Knoten 11");
    expect(query(graphCalls(calls)[0])).toBe(
      "mode=ego&center=11&center=12&center=15&center=13&depth=2&hide_lists=true",
    );
    for (const name of ["Anna Keller", "Jonas Brandt", "Peter Hofmann", "Dr. Miriam Steiner"]) {
      expect(screen.getByRole("button", { name: `Zentrum entfernen: ${name}` })).toBeTruthy();
    }
    expect(screen.getByLabelText("Tiefe")).toHaveProperty("value", "2");
  });

  it("asks for the live size of a draft and draws it only on request", async () => {
    const { router, calls } = renderApp("/karte?center=11");
    await screen.findByText("Knoten 11");
    expect(graphCalls(calls)).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Mindestanzahl genau"), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Cc-Beteiligung mitzählen" }));
    expect(screen.getByText("≥ 25")).toBeTruthy();
    await waitFor(() =>
      expect(sizeCalls(calls).map(query)).toContain(
        "mode=ego&center=11&min_edge=25&cc=true&hide_lists=true",
      ),
    );
    expect(screen.getByText("Geänderte Einstellungen, noch nicht gezeichnet.")).toBeTruthy();
    expect(graphCalls(calls)).toHaveLength(1);
    expect(search(router)).toBe("?center=11");

    fireEvent.click(screen.getByRole("button", { name: "Karte zeichnen" }));
    expect(search(router)).toBe("?center=11&min=25&cc=1");
    await waitFor(() => expect(graphCalls(calls)).toHaveLength(2));
    expect(query(graphCalls(calls)[1])).toBe(
      "mode=ego&center=11&min_edge=25&cc=true&hide_lists=true",
    );
  });

  it("warns in the preview when the draft is too large", async () => {
    renderApp("/karte", (call) =>
      call.url.pathname === "/api/graph/size"
        ? { nodes: 5412, edges: 30123, mails: 99000, too_large: true }
        : fixtureApi(call),
    );
    expect(
      await screen.findByText("Ergibt 5.412 Knoten, höchstens 2.000 sind möglich."),
    ).toBeTruthy();
  });

  it("applies layout, colours and arrows at once without loading again", async () => {
    const { router, calls } = renderApp("/karte");
    await screen.findByText("Knoten 11");
    fireEvent.click(screen.getByRole("checkbox", { name: "Richtung als Pfeile zeigen" }));
    fireEvent.change(screen.getByLabelText("Layout"), { target: { value: "circle" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Nach Domain einfärben" }));
    expect(search(router)).toBe("?layout=circle&color=0&arrows=1");
    expect(screen.queryByRole("list", { name: "Domainfarben" })).toBeNull();
    expect(screen.queryByText("Geänderte Einstellungen, noch nicht gezeichnet.")).toBeNull();
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(graphCalls(calls)).toHaveLength(1);
  });

  it("sends two domains in the domains mode", async () => {
    const { router, calls } = renderApp("/karte");
    await screen.findByText("Knoten 11");
    fireEvent.click(screen.getByRole("radio", { name: /Zwei Domains gegenüber/ }));
    // Prefilled with the two biggest sender domains.
    expect(screen.getByLabelText("Erste Domain")).toHaveProperty("value", "nordlicht-gmbh.example");
    fireEvent.change(screen.getByLabelText("Zweite Domain"), {
      target: { value: "Kanzlei-Muster.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Karte zeichnen" }));
    expect(search(router)).toBe(
      "?mode=domains&domain=nordlicht-gmbh.example,kanzlei-muster.example",
    );
    await waitFor(() => expect(graphCalls(calls)).toHaveLength(2));
    expect(query(graphCalls(calls)[1])).toBe(
      "mode=domains&domain=nordlicht-gmbh.example&domain=kanzlei-muster.example&hide_lists=true",
    );
  });

  it("shows the selected node's figures, connections and actions", async () => {
    const { router } = renderApp("/karte?center=11");
    expect(screen.getByText(/Klick auf einen Knoten zeigt hier/)).toBeTruthy();
    fireEvent.click(await screen.findByText("Knoten 12"));

    const panel = screen.getByRole("complementary", { name: "Ausgewählte Person" });
    expect(within(panel).getByText("Jonas Brandt")).toBeTruthy();
    const tile = (label: string) => within(panel).getByText(label).nextElementSibling?.textContent;
    expect(tile("Mails gesamt")).toBe("2.210");
    expect(tile("Kontakte")).toBe("58");
    expect(tile("Im Ausschnitt")).toBe("3 Kanten");
    expect(tile("Zentralität")).toBe("0,38");

    const links = within(panel)
      .getAllByRole("link")
      .filter((link) => link.closest("li"));
    expect(links.map((link) => link.textContent)).toEqual([
      "Anna Keller→ 178 · ← 210",
      "Peter Hofmann→ 140 · ← 120",
      "Dr. Miriam Steiner→ 12 · ← 9",
    ]);
    expect(links[0].getAttribute("href")).toBe("/mails?between=12&between=11");
    expect(within(panel).getByRole("link", { name: "Profil öffnen" }).getAttribute("href")).toBe(
      "/personen/12",
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Nachbarn aufklappen" }));
    expect(search(router)).toBe("?center=11&expand=12");
    expect(await screen.findByText(/1 aufgeklappt/)).toBeTruthy();
    fireEvent.click(await screen.findByText("Knoten 12"));
    fireEvent.click(screen.getByRole("button", { name: "Knoten ausblenden" }));
    expect(search(router)).toBe("?center=11&expand=12&hide=12");
    expect(screen.getByText(/Klick auf einen Knoten zeigt hier/)).toBeTruthy();
  });

  it("marks lists, counts Cc when asked and offers no hiding for centers", async () => {
    renderApp("/karte?center=11&cc=1");
    fireEvent.click(await screen.findByText("Knoten 19"));
    const panel = screen.getByRole("complementary", { name: "Ausgewählte Person" });
    expect(within(panel).getByText("Verteiler")).toBeTruthy();

    fireEvent.click(screen.getByText("Knoten 11"));
    expect(within(panel).getByText("Anna Keller")).toBeTruthy();
    expect(within(panel).getByText("→ 210 · ← 178 · Cc 12")).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: "Knoten ausblenden" })).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: "Auswahl aufheben" }));
    expect(screen.getByText(/Klick auf einen Knoten zeigt hier/)).toBeTruthy();
  });

  it("explains an excerpt above the limit", async () => {
    renderApp(
      "/karte?limit=2000",
      failWith("/api/graph", 400, "graph_too_large", "the excerpt has 2410 nodes"),
    );
    expect(await screen.findByText("Der Ausschnitt hätte mehr als 2.000 Personen.")).toBeTruthy();
    expect(
      screen.getByText("Mindestanzahl Mails erhöhen, Tiefe verringern oder Zeitraum eingrenzen."),
    ).toBeTruthy();
    expect(screen.getByText("Noch keine Karte")).toBeTruthy();
  });

  it("keeps the center's name when a deeper excerpt is refused", async () => {
    renderApp("/karte?center=11", (call) =>
      call.url.pathname === "/api/graph" && call.url.searchParams.get("depth") === "3"
        ? Response.json({ detail: { code: "graph_too_large", message: "" } }, { status: 400 })
        : fixtureApi(call),
    );
    await screen.findByText("Knoten 11");
    fireEvent.change(screen.getByRole("combobox", { name: "Tiefe" }), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Karte zeichnen" }));
    expect(await screen.findByText("Der Ausschnitt hätte mehr als 2.000 Personen.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zentrum entfernen: Anna Keller" })).toBeTruthy();
  });

  it("explains an unknown center and other errors", async () => {
    renderApp("/karte?center=999", failWith("/api/graph", 404, "not_found", "person 999"));
    expect(await screen.findByText("Person nicht gefunden")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zur Übersicht" }).getAttribute("href")).toBe("/karte");
  });

  it("shows an empty excerpt with a hint", async () => {
    const lonely: Graph = {
      ...graphFixture,
      nodes: graphFixture.nodes.slice(0, 1),
      edges: [],
      mails: 0,
    };
    renderApp("/karte?center=11&min=500", (call) =>
      call.url.pathname === "/api/graph" ? lonely : fixtureApi(call),
    );
    expect(await screen.findByText("Keine Verbindungen in diesem Ausschnitt")).toBeTruthy();
    expect(screen.getByText(/Mindestanzahl Mails pro Kante senken/)).toBeTruthy();
  });

  it("adds a center from the person search and falls back to top without centers", async () => {
    const { router, calls } = renderApp("/karte");
    await screen.findByText("Knoten 11");
    fireEvent.click(screen.getByRole("radio", { name: /Ego-Netzwerk/ }));
    expect(screen.getByText("Mindestens eine Person als Zentrum hinzufügen.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Karte zeichnen" })).toHaveProperty("disabled", true);

    const field = screen.getByRole("combobox", { name: "Zentrum" });
    fireEvent.change(field, { target: { value: "Stein" } });
    const option = await screen.findByRole("option", { name: /Stefan Steinbach/ });
    expect(option.textContent).toContain("233 Mails");
    const persons = calls.find((call) => call.url.pathname === "/api/persons")!;
    expect(query(persons)).toBe("q=Stein&limit=8");
    fireEvent.click(option);
    expect(
      screen.getByRole("button", { name: "Zentrum entfernen: Stefan Steinbach" }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Karte zeichnen" }));
    expect(search(router)).toBe("?center=21");

    fireEvent.click(await screen.findByRole("button", { name: /Zentrum entfernen/ }));
    expect(screen.getByRole("radio", { name: /Top-N/ })).toHaveProperty("checked", true);
  });

  it("explains a missing person search instead of breaking", async () => {
    renderApp("/karte?center=11", (call) =>
      call.url.pathname === "/api/persons"
        ? Response.json({ detail: "Not Found" }, { status: 404 })
        : fixtureApi(call),
    );
    fireEvent.change(await screen.findByRole("combobox", { name: "Zentrum" }), {
      target: { value: "Anna" },
    });
    expect(await screen.findByText(/Die Personensuche ist noch nicht verfügbar/)).toBeTruthy();
  });

  it("plays the years one by one and stops at the year shown", async () => {
    const { router, calls } = renderApp("/karte?from=2024&to=2026");
    await screen.findByText("Knoten 11");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(screen.getByRole("button", { name: /Zeitverlauf abspielen/ }));
    await waitFor(() =>
      expect(graphCalls(calls).map(query)).toContain(
        "mode=top&year_from=2024&year_to=2024&hide_lists=true",
      ),
    );
    expect(screen.getByText("2024", { selector: "div" })).toBeTruthy();
    await act(() => vi.advanceTimersByTimeAsync(1600));
    await waitFor(() => expect(screen.getByText("2025", { selector: "div" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "■ Anhalten bei 2025" }));
    expect(search(router)).toBe("?from=2025&to=2025");
  });
});
