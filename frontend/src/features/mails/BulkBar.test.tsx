import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkRequest, MailSummary } from "../../api/types";
import { filteredQuery, mailItems, summaryFiltered } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import type { ExportDialogProps } from "../research/ExportDialog";

// The export dialog is the Akten screen's; here it only matters what it is opened with.
const exportDialog = vi.hoisted(() => ({ props: [] as unknown[] }));
vi.mock("../research/ExportDialog", () => ({
  ExportDialog: (props: ExportDialogProps) => {
    exportDialog.props.push(props);
    return null;
  },
}));

const filteredPath = `/mails?${new URLSearchParams({ q: filteredQuery })}`;

/** The fixture backend with bulk changes, and the list's summary when one is given. */
function bulkApi(summary?: MailSummary) {
  return (call: ApiCall): unknown => {
    if (call.url.pathname === "/api/mails/bulk") {
      const request = call.body as BulkRequest;
      return request.ids
        ? { mails: request.ids.length, changed: request.ids.length }
        : { mails: 1207, changed: 1200 };
    }
    if (summary && call.url.pathname === "/api/mails/summary") return summary;
    return fixtureApi(call);
  };
}

const rowBox = (subject: string) => screen.getByRole("checkbox", { name: `Auswählen: ${subject}` });
const bulkCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/mails/bulk");
const bar = () => screen.getByRole("region", { name: "Auswahl" });

function openMenu(label: string): HTMLElement {
  fireEvent.click(within(bar()).getByRole("button", { name: `${label} ▾` }));
  return within(bar()).getByRole("group", { name: label });
}

describe("selection and bulk changes in the mail list", () => {
  beforeEach(() => {
    exportDialog.props = [];
  });

  it("shows status, tags and notes per row", async () => {
    renderApp("/mails");
    const first = (await screen.findByRole("link", { name: mailItems[0].subject! })).closest("tr")!;
    expect(within(first).getByRole("img", { name: "Status: Relevant" }).getAttribute("title")).toBe(
      "Relevant",
    );
    expect(
      within(first).getByRole("img", { name: "Schlagwörter: Spendenaffären, Vertrag Nordstahl" }),
    ).toBeTruthy();
    expect(within(first).getByRole("img", { name: "2 Notizen" }).textContent).toBe("2");
    const fourth = screen.getByRole("link", { name: mailItems[3].subject! }).closest("tr")!;
    expect(within(fourth).getByRole("img", { name: "Status: Gesichtet" })).toBeTruthy();
    expect(within(fourth).queryByRole("img", { name: /Notiz/ })).toBeNull();
  });

  it("selects by checkbox without opening the mail, and a page at once", async () => {
    const { router } = renderApp("/mails");
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[0].subject!));
    expect(router.state.location.pathname).toBe("/mails");
    expect(within(bar()).getByText("1 ausgewählt")).toBeTruthy();
    expect(within(bar()).getByText("1 ausgewählt").getAttribute("title")).toContain(
      "zurückgesetzt, wenn sich Filter, Suche, Sortierung oder Seite ändern",
    );

    const page = screen.getByRole("checkbox", { name: "Alle Mails dieser Seite auswählen" });
    expect(page).toHaveProperty("indeterminate", true);
    fireEvent.click(page);
    expect(within(bar()).getByText("12 ausgewählt")).toBeTruthy();
    fireEvent.click(page);
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();

    // A click elsewhere in the row still opens the mail.
    fireEvent.click(screen.getByText("Vertrag gekündigt?").closest("tr")!.lastElementChild!);
    expect(router.state.location.pathname).toBe("/mails/183590");
  });

  it("changes the selected mails by id and then clears the selection", async () => {
    const { calls } = renderApp("/mails", bulkApi());
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[0].subject!));
    fireEvent.click(rowBox(mailItems[2].subject!));
    const menu = openMenu("Schlagwort");
    fireEvent.click(
      await within(menu).findByRole("button", { name: "Schlagwort „Spendenaffären“ hinzufügen" }),
    );
    expect(await screen.findByText("2 Mails geändert")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();
    expect(rowBox(mailItems[0].subject!)).toHaveProperty("checked", false);

    fireEvent.click(rowBox(mailItems[3].subject!));
    fireEvent.click(
      within(openMenu("Akte")).getByRole("button", {
        name: "Aus Akte „Story Nordstahl“ entfernen",
      }),
    );
    await waitFor(() => expect(bulkCalls(calls)).toHaveLength(2));
    fireEvent.click(rowBox(mailItems[3].subject!));
    fireEvent.click(within(openMenu("Status setzen")).getByRole("button", { name: "Ungesichtet" }));
    await waitFor(() => expect(bulkCalls(calls)).toHaveLength(3));
    fireEvent.click(rowBox(mailItems[3].subject!));
    fireEvent.click(
      within(openMenu("Markierung")).getByRole("button", { name: "Markierung entfernen" }),
    );
    await waitFor(() => expect(bulkCalls(calls)).toHaveLength(4));

    expect(bulkCalls(calls).map((call) => [call.method, call.body])).toEqual([
      ["POST", { ids: [184221, 184133], action: "tag_add", tag_id: 2 }],
      ["POST", { ids: [184102], action: "collection_remove", collection_id: 1 }],
      ["POST", { ids: [184102], action: "review", review: null }],
      ["POST", { ids: [184102], action: "flag", flagged: false }],
    ]);
  });

  it("selects every match after asking and sends the filters", async () => {
    const { calls } = renderApp(filteredPath, bulkApi());
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[1].subject!));
    fireEvent.click(
      await within(bar()).findByRole("button", { name: "Alle 1.207 Treffer auswählen" }),
    );
    expect(within(bar()).getByText("Wirklich alle 1.207 Treffer auswählen?")).toBeTruthy();
    fireEvent.click(within(bar()).getByRole("button", { name: "Alle auswählen" }));
    expect(within(bar()).getByText("Alle 1.207 Treffer ausgewählt")).toBeTruthy();
    expect(rowBox(mailItems[5].subject!)).toHaveProperty("checked", true);

    fireEvent.click(within(openMenu("Status setzen")).getByRole("button", { name: "Relevant" }));
    expect(await screen.findByText("1.200 von 1.207 Mails geändert")).toBeTruthy();
    expect(bulkCalls(calls)[0].body).toEqual({
      filters: { q: filteredQuery },
      action: "review",
      review: "relevant",
    });
  });

  it("does not offer every match above the bulk limit", async () => {
    renderApp(filteredPath, bulkApi({ ...summaryFiltered, total: 60_000 }));
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[1].subject!));
    expect(
      await within(bar()).findByText(
        "Alle 60.000 Treffer sind zu viele für eine Änderung (höchstens 50.000).",
      ),
    ).toBeTruthy();
    expect(within(bar()).queryByRole("button", { name: /Treffer auswählen/ })).toBeNull();
  });

  it("names the backend's refusal when an inexact number was too many", async () => {
    const api = bulkApi({ ...summaryFiltered, total: 10_000, exact: false });
    const { calls } = renderApp(filteredPath, (call) =>
      call.url.pathname === "/api/mails/bulk"
        ? Response.json(
            { detail: { code: "too_many_mails", message: "62000 mails" } },
            { status: 400 },
          )
        : api(call),
    );
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[1].subject!));
    fireEvent.click(
      await within(bar()).findByRole("button", {
        name: "Alle Treffer (mehr als 10.000) auswählen",
      }),
    );
    fireEvent.click(within(bar()).getByRole("button", { name: "Alle auswählen" }));
    fireEvent.click(within(openMenu("Markierung")).getByRole("button", { name: "Markieren" }));
    expect(
      await within(bar()).findByText(
        "Zu viele Mails: Eine Änderung erfasst höchstens 50.000. Bitte die Suche eingrenzen.",
      ),
    ).toBeTruthy();
    expect(bulkCalls(calls)[0].body).toEqual({
      filters: { q: filteredQuery },
      action: "flag",
      flagged: true,
    });
  });

  it("starts empty when sort or page change", async () => {
    renderApp("/mails");
    await screen.findAllByRole("row");
    fireEvent.click(rowBox(mailItems[0].subject!));
    fireEvent.change(screen.getByLabelText("Sortierung"), { target: { value: "date_asc" } });
    await waitFor(() => expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull());
    fireEvent.click(rowBox(mailItems[0].subject!));
    fireEvent.click(screen.getByRole("link", { name: "Weiter ›" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull());
  });

  it("opens the export for the whole filter or for the selection", async () => {
    renderApp(filteredPath);
    await screen.findAllByRole("row");
    fireEvent.click(screen.getByRole("button", { name: "Exportieren" }));
    await waitFor(() => expect(exportDialog.props).not.toHaveLength(0));
    expect(exportDialog.props.at(-1)).toEqual({
      selection: { filters: { q: filteredQuery } },
      count: 1207,
      label: filteredQuery,
      onClose: expect.any(Function),
    });

    (exportDialog.props.at(-1) as ExportDialogProps).onClose();
    fireEvent.click(rowBox(mailItems[0].subject!));
    fireEvent.click(rowBox(mailItems[1].subject!));
    fireEvent.click(within(bar()).getByRole("button", { name: "Exportieren" }));
    await waitFor(() =>
      expect(exportDialog.props.at(-1)).toEqual({
        selection: { ids: [184221, 184190] },
        count: 2,
        label: filteredQuery,
        onClose: expect.any(Function),
      }),
    );
  });
});
