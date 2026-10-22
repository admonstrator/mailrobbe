import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DocumentDetail, PasswordFinding, PasswordTryResult } from "../../api/types";
import { setEditor } from "../../lib/editor";
import { lockedDocument, openedDocument } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { OPENED_SHOWN } from "./ProtectionCard";

function protectionCard(): HTMLElement {
  return screen.getByRole("heading", { name: /^Verschlüsselt/ }).closest("section")!;
}

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method === "POST");

/** The fact of a row of label and value in the card. */
function fact(card: HTMLElement, label: string): HTMLElement {
  return within(card).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
}

/** Holds the answer of the try on every locked document until released. */
function holdEverywhere(): () => void {
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  const inner = globalThis.fetch;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input) === "/api/documents/passwords") await held;
    return inner(input, init);
  });
  return release;
}

async function typePassword(password: string) {
  const field = await screen.findByRole("textbox", { name: "Kennwort ausprobieren" });
  fireEvent.change(field, { target: { value: password } });
  return field;
}

describe("a locked document", () => {
  it("says it is encrypted, what the imports tried, and offers no preview", async () => {
    renderApp("/anhaenge/5104");
    const card = await screen.findByRole("heading", { name: "Verschlüsselt" });
    const section = card.closest("section")!;
    expect(section.closest("main")).toBeTruthy();
    expect(within(section).getByRole("img", { name: /Kennwort ist nicht bekannt/ })).toBeTruthy();
    expect(section.textContent).toContain(
      "Die Datei ist verschlüsselt, das Kennwort ist nicht bekannt.",
    );
    expect(section.textContent).toContain(
      "Die Importe haben 14 Kennwörter aus dem Archiv an ihr probiert, zuletzt am 20.10.2026 03:23.",
    );
    expect(screen.getByText("Keine Vorschau, solange das Kennwort fehlt.")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Vorschau" })).toBeNull();
    expect(
      screen.getByText(
        "Die Datei ist mit einem Kennwort geschützt. Ohne das Kennwort lässt sich ihr Text nicht lesen.",
      ),
    ).toBeTruthy();
    // No decrypted bytes without a password.
    expect(screen.queryByRole("link", { name: "Entschlüsselt herunterladen" })).toBeNull();
  });

  it("says when no password was tried yet", async () => {
    renderApp("/anhaenge/5104", (call) =>
      call.url.pathname === "/api/documents/5104"
        ? { ...lockedDocument, password_tries: 0, password_tried_at: null }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Verschlüsselt" });
    expect(protectionCard().textContent).toContain("Bisher wurde kein Kennwort an ihr probiert.");
  });

  it("says when Mailrobbe cannot open the format yet, and offers no field", async () => {
    renderApp("/anhaenge/5104", (call) =>
      call.url.pathname === "/api/documents/5104"
        ? { ...lockedDocument, password_trial: false, password_tries: 0 }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Verschlüsselt" });
    expect(protectionCard().textContent).toContain(
      "Dateien dieses Formats kann Mailrobbe noch nicht öffnen (etwa verschlüsselte OpenDocument-Dateien)",
    );
    expect(screen.queryByRole("textbox", { name: "Kennwort ausprobieren" })).toBeNull();
  });

  it("tries a typed-in password in plain text and says it is kept for later imports", async () => {
    setEditor("Lena Vogt");
    const { calls } = renderApp("/anhaenge/5104");
    const field = await typePassword("  Geheim-2019 ");
    // Shown as typed: found passwords are evidence (D208).
    expect(field.getAttribute("type")).toBe("text");
    expect(field.getAttribute("autocomplete")).toBe("off");
    const card = protectionCard();
    expect(card.textContent).toContain("Wird gespeichert als Lena Vogt.");
    expect(
      within(card).getByRole("checkbox", { name: "an allen verschlüsselten Dateien probieren" }),
    ).toHaveProperty("checked", false);

    fireEvent.click(within(card).getByRole("button", { name: "Probieren" }));
    expect(
      await within(card).findByText(
        "Das Kennwort öffnet diese Datei nicht. Das Kennwort bleibt gespeichert; spätere Importe probieren es an neu gefundenen verschlüsselten Dateien.",
      ),
    ).toBeTruthy();
    const [write] = writes(calls);
    expect(write.url.pathname).toBe("/api/documents/5104/password");
    expect(write.body).toEqual({ password: "Geheim-2019" });
    expect(write.headers.get("X-Mailrobbe-Editor")).toBe("Lena%20Vogt");
    // Nothing opened: nothing to load again.
    expect(calls.filter((call) => call.url.pathname === "/api/documents/5104")).toHaveLength(1);
  });

  it("loads the page again once the password opened it, and shows the open state", async () => {
    setEditor("Lena Vogt");
    let opened = false;
    const typed: DocumentDetail = {
      ...lockedDocument,
      protection: "open",
      text_status: "text",
      password: {
        value: "Geheim-2019",
        tier: "typed",
        found_at: "2026-10-22T13:05:00Z",
        found_by: "Lena Vogt",
        finding: {
          id: 90,
          context: "",
          mail: null,
          recipients: [],
          document: null,
          editor: "Lena Vogt",
          created_at: "2026-10-22T13:05:00Z",
        },
      },
    };
    const { calls } = renderApp("/anhaenge/5104", (call) => {
      if (call.url.pathname === "/api/documents/5104/password") {
        opened = true;
        return { tried: 1, opened: [5104], errors: 0 } satisfies PasswordTryResult;
      }
      if (call.url.pathname === "/api/documents/5104") return opened ? typed : lockedDocument;
      return fixtureApi(call);
    });
    await typePassword("Geheim-2019");
    fireEvent.click(screen.getByRole("button", { name: "Probieren" }));

    expect(await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" })).toBeTruthy();
    const card = protectionCard();
    expect(within(card).getByText("Das Kennwort hat die Datei geöffnet.")).toBeTruthy();
    expect(card.textContent).toContain("Geöffnet mit dem Kennwort »Geheim-2019«");
    expect(fact(card, "Herkunft").textContent).toBe("Auf dieser Seite eingegeben von Lena Vogt");
    expect(fact(card, "Beleg").textContent).toBe("Eingegeben am 22.10.2026 15:05");
    expect(screen.queryByRole("textbox", { name: "Kennwort ausprobieren" })).toBeNull();
    expect(calls.filter((call) => call.url.pathname === "/api/documents/5104")).toHaveLength(2);
  });

  it("tries it on every locked document, says so while it works, and links what it opened", async () => {
    const { calls } = renderApp("/anhaenge/5104");
    await typePassword("Sommer2019!");
    const release = holdEverywhere();
    const card = protectionCard();
    fireEvent.click(
      within(card).getByRole("checkbox", { name: "an allen verschlüsselten Dateien probieren" }),
    );
    fireEvent.click(within(card).getByRole("button", { name: "Probieren" }));
    expect(
      await within(card).findByText(
        "Wird an allen verschlüsselten Dateien probiert. Bei einem großen Archiv kann das eine Minute dauern.",
      ),
    ).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Probieren" })).toHaveProperty(
      "disabled",
      true,
    );
    release();

    const answer = await within(card).findByText(
      "An 87 Dateien probiert, 2 geöffnet, 1 nicht lesbar:",
    );
    const links = within(answer.parentElement!).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/anhaenge/5110",
      "/anhaenge/5106",
    ]);
    // Named once their pages are loaded.
    await waitFor(() =>
      expect(links.map((link) => link.textContent)).toEqual([
        "Angebot_Nordstahl.pdf",
        "Unterlagen.zip",
      ]),
    );
    const [write] = writes(calls);
    expect(write.url.pathname).toBe("/api/documents/passwords");
    expect(write.body).toEqual({ password: "Sommer2019!" });
  });

  it("counts what it opened beyond the first ones", async () => {
    const many = Array.from({ length: OPENED_SHOWN + 3 }, (_, index) => 7000 + index);
    renderApp("/anhaenge/5104", (call) =>
      call.url.pathname === "/api/documents/passwords"
        ? ({ tried: 900, opened: many, errors: 0 } satisfies PasswordTryResult)
        : fixtureApi(call),
    );
    await typePassword("Sommer2019!");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "an allen verschlüsselten Dateien probieren" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Probieren" }));
    const rest = await screen.findByRole("link", { name: "und 3 weitere" });
    expect(rest.getAttribute("href")).toBe("/anhaenge?protection=open");
    expect(screen.getByText("An 900 Dateien probiert, 23 geöffnet:")).toBeTruthy();
    // Unknown documents keep their number.
    expect(screen.getByRole("link", { name: "Dokument #7000" })).toBeTruthy();
  });

  it("says so when the document was opened meanwhile, and shows how it stands now", async () => {
    let opened = false;
    renderApp("/anhaenge/5104", (call) => {
      if (call.url.pathname === "/api/documents/5104/password") {
        opened = true;
        return Response.json(
          { detail: { code: "not_locked", message: "not locked" } },
          { status: 409 },
        );
      }
      if (call.url.pathname === "/api/documents/5104") {
        return opened ? { ...openedDocument, id: 5104 } : lockedDocument;
      }
      return fixtureApi(call);
    });
    await typePassword("Sommer2019!");
    fireEvent.click(screen.getByRole("button", { name: "Probieren" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Die Datei braucht kein Kennwort mehr: Inzwischen wurde sie geöffnet. Die Seite zeigt den neuen Stand.",
    );
    expect(await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" })).toBeTruthy();
  });
});

describe("an opened document", () => {
  it("shows the password with where it was found, and both downloads", async () => {
    renderApp("/anhaenge/5110");
    const heading = await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" });
    const card = heading.closest("section")!;
    expect(
      within(card).getByRole("img", { name: /mit einem gefundenen Kennwort geöffnet/ }),
    ).toBeTruthy();
    expect(card.textContent).toContain("Geöffnet mit dem Kennwort »Sommer2019!«");
    expect(fact(card, "Herkunft").textContent).toBe("Gefunden in einer Mail desselben Verlaufs");
    expect(fact(card, "Geöffnet").textContent).toBe("20.10.2026 03:23");

    const evidence = fact(card, "Beleg");
    const mail = within(evidence).getByRole("link", { name: "Mail vom 15.10.2026 17:48" });
    expect(mail.getAttribute("href")).toBe("/mails/184133");
    expect(mail.getAttribute("title")).toBe("Re: Prüfung Vertragsklauseln §§ 4–7");
    expect(evidence.textContent).toContain(
      "Mail vom 15.10.2026 17:48 von Dr. Miriam Steiner an Jonas Brandt, Anna Keller",
    );
    expect(
      within(evidence).getByRole("link", { name: "Dr. Miriam Steiner" }).getAttribute("href"),
    ).toBe("/personen/13");
    // The line it stands in, as written, with the password marked.
    const quote = evidence.querySelector("blockquote")!;
    expect(quote.textContent).toBe(
      "das Kennwort für das Angebot lautet Sommer2019! – bitte nicht weitergeben.",
    );
    expect(quote.querySelector("mark")!.textContent).toBe("Sommer2019!");

    expect(screen.getByRole("link", { name: "Herunterladen" }).getAttribute("href")).toBe(
      "/api/attachments/9110/content",
    );
    const decrypted = screen.getByRole("link", { name: "Entschlüsselt herunterladen" });
    expect(decrypted.getAttribute("href")).toBe("/api/attachments/9110/content?decrypted=true");
    expect(decrypted.hasAttribute("download")).toBe(true);
    expect(screen.queryByRole("textbox", { name: "Kennwort ausprobieren" })).toBeNull();
  });

  it.each([
    ["mail", null, "Gefunden in derselben Mail"],
    [
      "contacts",
      null,
      "Gefunden in einer Mail zwischen denselben Personen, bis 30 Tage davor oder danach",
    ],
    [
      "attachments",
      null,
      "Gefunden im Text eines Anhangs aus demselben Verlauf oder zwischen denselben Personen",
    ],
    ["opened", null, "Hat schon eine andere Datei geöffnet"],
    ["archive", null, "Gefunden anderswo im Archiv"],
    [
      "manual",
      "Lena Vogt",
      "Von Hand eingegeben von Lena Vogt und an allen verschlüsselten Dateien probiert",
    ],
    ["typed", null, "Auf dieser Seite eingegeben (ohne Namen)"],
  ] as const)("says where a password of tier %s came from", async (tier, editor, text) => {
    const password = openedDocument.password!;
    renderApp("/anhaenge/5110", (call) =>
      call.url.pathname === "/api/documents/5110"
        ? {
            ...openedDocument,
            password: { ...password, tier, finding: { ...password.finding!, editor } },
          }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" });
    expect(fact(protectionCard(), "Herkunft").textContent).toBe(text);
  });

  /** The opened offer with the password found elsewhere. */
  const withFinding = (finding: PasswordFinding | null) => (call: ApiCall) =>
    call.url.pathname === "/api/documents/5110"
      ? { ...openedDocument, password: { ...openedDocument.password!, finding } }
      : fixtureApi(call);

  it("links the document whose text holds the password", async () => {
    renderApp(
      "/anhaenge/5110",
      withFinding({
        ...openedDocument.password!.finding!,
        mail: null,
        recipients: [],
        document: { id: 5101, name: "Rahmenvereinbarung_2026_final.pdf" },
      }),
    );
    await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" });
    const evidence = fact(protectionCard(), "Beleg");
    expect(evidence.textContent).toMatch(/^Im Text von Rahmenvereinbarung_2026_final\.pdf/);
    expect(
      within(evidence)
        .getByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" })
        .getAttribute("href"),
    ).toBe("/anhaenge/5101");
  });

  it("says when it is not known where the password was found", async () => {
    renderApp("/anhaenge/5110", withFinding(null));
    await screen.findByRole("heading", { name: "Verschlüsselt und geöffnet" });
    expect(fact(protectionCard(), "Beleg").textContent).toBe(
      "Wo es gefunden wurde, ist nicht bekannt.",
    );
  });

  it("previews an opened PDF decrypted", async () => {
    const { calls } = renderApp("/anhaenge/5110");
    expect(await screen.findByTitle("PDF-Vorschau von Angebot_Nordstahl.pdf")).toBeTruthy();
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/attachments/9110/content" &&
            call.url.searchParams.get("decrypted") === "true",
        ),
      ).toBe(true),
    );
    expect(
      calls.filter(
        (call) => call.url.pathname === "/api/attachments/9110/content" && !call.url.search,
      ),
    ).toHaveLength(0);
  });

  it("explains when the decrypted preview cannot be made", async () => {
    renderApp("/anhaenge/5110", (call) =>
      call.url.pathname === "/api/attachments/9110/content"
        ? Response.json(
            { detail: { code: "decrypt_failed", message: "Bad password for PDF" } },
            { status: 422 },
          )
        : fixtureApi(call),
    );
    expect(
      await screen.findByText(
        "Die Datei ließ sich mit dem gefundenen Kennwort nicht entschlüsseln. Herunterladen geht trotzdem.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Bad password for PDF")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Erneut versuchen" })).toBeNull();
  });

  it("explains when no password is known for the decrypted preview", async () => {
    renderApp("/anhaenge/5110", (call) =>
      call.url.pathname === "/api/attachments/9110/content"
        ? Response.json({ detail: { code: "not_locked", message: "no password" } }, { status: 409 })
        : fixtureApi(call),
    );
    expect(
      await screen.findByText(
        "Für diese Datei ist kein Kennwort gefunden, eine entschlüsselte Vorschau gibt es nicht.",
      ),
    ).toBeTruthy();
  });
});
