import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EVIDENCE_FILE_LIMIT, type ErrorCode } from "../../api/types";
import { setEditor } from "../../lib/editor";
import { s2019Name } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const PATH = `/import/selektoren/${s2019Name}`;
const KEYS_URL = `/api/dkim/selectors/${s2019Name}/keys`;

const keyPosts = (calls: ApiCall[]) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === KEYS_URL);
const apiError = (status: number, code: ErrorCode, message = "refused") =>
  Response.json({ detail: { code, message } }, { status });

async function openForm(api: (call: ApiCall) => unknown = fixtureApi) {
  const rendered = renderApp(PATH, api);
  fireEvent.click(await screen.findByRole("button", { name: "Schlüssel von Hand hinzufügen" }));
  const dialog = screen.getByRole("dialog", { name: "Schlüssel von Hand hinzufügen" });
  return { ...rendered, dialog };
}

function fill(dialog: HTMLElement, label: string | RegExp, value: string) {
  fireEvent.change(within(dialog).getByLabelText(label), { target: { value } });
}

function chooseFile(dialog: HTMLElement, file: File) {
  const input = within(dialog).getByLabelText(/Belegdatei/);
  fireEvent.change(input, { target: { files: [file] } });
}

const submit = (dialog: HTMLElement) =>
  fireEvent.click(within(dialog).getByRole("button", { name: "Schlüssel hinzufügen" }));

afterEach(() => {
  setEditor(""); // the page's copy outlives the cleared storage
});

describe("manual key", () => {
  it("asks for the key and where it comes from before sending", async () => {
    const { dialog, calls } = await openForm();
    submit(dialog);
    expect(within(dialog).getByRole("alert").textContent).toBe("Bitte den Schlüssel eintragen.");

    fill(dialog, /Schlüssel \(TXT-Eintrag/, "p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5");
    submit(dialog);
    expect(within(dialog).getByRole("alert").textContent).toBe(
      "Bitte angeben, woher der Schlüssel stammt.",
    );

    fill(dialog, "Herkunft", "Zonendatei vom Hoster");
    fill(dialog, "von", "2020-01-01");
    fill(dialog, "bis", "2019-01-01");
    submit(dialog);
    expect(within(dialog).getByRole("alert").textContent).toBe("„Bis“ liegt vor „Von“.");
    expect(keyPosts(calls)).toHaveLength(0);
  });

  it("refuses an evidence file over the limit before sending", async () => {
    const { dialog, calls } = await openForm();
    const big = new File(["x"], "zonen-export.tar", { type: "application/x-tar" });
    Object.defineProperty(big, "size", { value: EVIDENCE_FILE_LIMIT + 1 });
    chooseFile(dialog, big);
    expect(within(dialog).getByRole("alert").textContent).toBe(
      "Die Datei ist größer als 10 MB; so große Belege nimmt Mailrobbe nicht an.",
    );
    fill(dialog, /Schlüssel \(TXT-Eintrag/, "v=DKIM1; k=rsa; p=MIGf");
    fill(dialog, "Herkunft", "Zonendatei vom Hoster");
    submit(dialog);
    await waitFor(() =>
      expect(within(dialog).getByRole("alert").textContent).toMatch(/größer als 10 MB/),
    );
    expect(keyPosts(calls)).toHaveLength(0);
  });

  it("sends key, evidence and file with the editor's name", async () => {
    setEditor("Lena Vogt");
    const { dialog, calls } = await openForm();
    expect(within(dialog).getByText("Lena Vogt")).toBeTruthy();
    fill(
      dialog,
      /Schlüssel \(TXT-Eintrag/,
      "  v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5 ",
    );
    fill(dialog, "Herkunft", "/m/51d0c3a9e8f7b6a5");
    fill(dialog, /Notiz/, "Steht in der Mail des Hosters vom März 2019.");
    fill(dialog, "von", "2019-03-01");
    fill(dialog, "bis", "2020-12-31");
    chooseFile(dialog, new File(["abc"], "zone.txt", { type: "text/plain" }));
    submit(dialog);

    await waitFor(() => expect(keyPosts(calls)).toHaveLength(1));
    const [post] = keyPosts(calls);
    expect(post.body).toEqual({
      record: "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5",
      reference: "/m/51d0c3a9e8f7b6a5",
      note: "Steht in der Mail des Hosters vom März 2019.",
      observed_from: "2019-03-01T00:00:00Z",
      observed_to: "2020-12-31T00:00:00Z",
      file_name: "zone.txt",
      file_base64: "YWJj",
    });
    expect(post.headers.get("X-Mailrobbe-Editor")).toBe("Lena%20Vogt");
    expect(post.headers.get("Content-Type")).toBe("application/json");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(
      await screen.findByText(
        "Schlüssel hinzugefügt. Mailrobbe prüft die Mails dieses Selektors jetzt mit ihm; die Zahlen folgen, sobald die Prüfung fertig ist.",
      ),
    ).toBeTruthy();
  });

  it("sends without a file and without a name", async () => {
    const { dialog, calls } = await openForm();
    expect(within(dialog).getByText(/Ohne Namen gespeichert/)).toBeTruthy();
    fill(dialog, /Schlüssel \(TXT-Eintrag/, "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5");
    fill(dialog, "Herkunft", "Screenshot der Hoster-Oberfläche");
    submit(dialog);
    await waitFor(() => expect(keyPosts(calls)).toHaveLength(1));
    expect(keyPosts(calls)[0].body).toEqual({
      record: "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5",
      reference: "Screenshot der Hoster-Oberfläche",
      note: "",
      observed_from: null,
      observed_to: null,
      file_name: null,
      file_base64: null,
    });
    expect(keyPosts(calls)[0].headers.has("X-Mailrobbe-Editor")).toBe(false);
  });

  it("asks for the editor's name from the form", async () => {
    const { dialog } = await openForm();
    fireEvent.click(within(dialog).getByRole("button", { name: "Namen eintragen" }));
    const editor = screen.getByRole("dialog", { name: "Name für Notizen und Änderungen" });
    fireEvent.change(within(editor).getByLabelText("Name"), { target: { value: "Lena Vogt" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Speichern" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Name für Notizen und Änderungen" })).toBeNull(),
    );
    expect(within(dialog).getByText("Lena Vogt")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Namen ändern" })).toBeTruthy();
  });

  it("says when the backend finds no usable key", async () => {
    const { dialog } = await openForm((call) =>
      call.method === "POST" && call.url.pathname === KEYS_URL
        ? apiError(400, "invalid_key", "no usable key in the record")
        : fixtureApi(call),
    );
    fill(dialog, /Schlüssel \(TXT-Eintrag/, "v=DKIM1; p=kaputt");
    fill(dialog, "Herkunft", "Zonendatei vom Hoster");
    submit(dialog);
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "Kein gültiger Schlüssel. Erwartet wird ein DKIM-Eintrag wie „v=DKIM1; k=rsa; p=MIIB…“ oder nur der Wert nach p=.",
    );
    expect(screen.getByRole("dialog", { name: "Schlüssel von Hand hinzufügen" })).toBeTruthy();
  });
});
