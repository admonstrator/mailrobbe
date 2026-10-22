import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BlockInfo, BlockOverrideUpdate, MailText, TextSegment } from "../../api/types";
import type { SearchMarks } from "../../components/Highlighted";
import { fixtureApi, renderElement } from "../../test/render";
import { BodyCard } from "./BodyCard";

// Texts with the segments quotes.split_text gives them (tests/test_quotes.py has the rule).
const REPLY =
  "Hallo Jonas,\n\npasst so, ich schicke den Vertrag morgen.\n\n-- \nAnna Keller\n" +
  "Nordlicht GmbH\n\nAm 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Hallo Anna,\n" +
  "> anbei der Entwurf mit der Haftungsklausel.\n> Gruß Jonas\n";
const REPLY_SEGMENTS: TextSegment[] = [
  { kind: "text", start: 0, end: 57, lines: 2, folded: false },
  { kind: "signature", start: 57, end: 89, lines: 3, folded: true },
  { kind: "quote", start: 89, end: 206, lines: 4, folded: true },
];
const INLINE =
  "Hallo Peter,\n\n> Können wir den Termin auf Donnerstag legen?\nJa, Donnerstag 10 Uhr passt.\n" +
  "\n> Und bringst du die Unterlagen mit?\nMache ich.\n\nGruß Anna\n";
const INLINE_SEGMENTS: TextSegment[] = [
  { kind: "text", start: 0, end: 14, lines: 1, folded: false },
  { kind: "quote", start: 14, end: 60, lines: 1, folded: false },
  { kind: "text", start: 60, end: 90, lines: 1, folded: false },
  { kind: "quote", start: 90, end: 127, lines: 1, folded: false },
  { kind: "text", start: 127, end: 149, lines: 2, folded: false },
];
const FORWARD =
  "---------- Forwarded message ---------\nVon: Jonas Brandt <j.brandt@stadtwerke.example>\n" +
  "Date: Fr., 17. Okt. 2026 um 09:12\nSubject: Rechnung\nTo: <anna@nordlicht.example>\n\n" +
  "Bitte überweisen Sie den Betrag bis Monatsende.\n";
const EMOJI =
  "Danke \u{1F44D}, das passt.\n\nAm 17.10.2026 um 09:12 schrieb Jonas Brandt:\n" +
  "> Ist die Haftung so in Ordnung?\n";

function showText(text: string, segments: TextSegment[], marks?: SearchMarks) {
  const body: MailText = {
    text,
    truncated: false,
    source: "text/plain",
    has_html: false,
    segments,
  };
  renderElement(<BodyCard mailId={7} tab="text" onTab={() => {}} marks={marks} />, (call) =>
    call.url.pathname === "/api/mails/7/body" ? body : fixtureApi(call),
  );
}

describe("body card, text view", () => {
  it("folds the history and the signature, each with its line count", async () => {
    showText(REPLY, REPLY_SEGMENTS);
    expect(await screen.findByText(/passt so, ich schicke den Vertrag morgen\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Signatur einblenden (3 Zeilen)" })).toBeTruthy();
    const quote = screen.getByRole("button", { name: "Zitat einblenden (4 Zeilen)" });
    expect(quote.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/Nordlicht GmbH/)).toBeNull();
    expect(screen.queryByText(/anbei der Entwurf/)).toBeNull();

    fireEvent.click(quote);
    expect(screen.getByText(/anbei der Entwurf/).textContent).toBe(
      "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Hallo Anna,\n" +
        "> anbei der Entwurf mit der Haftungsklausel.\n> Gruß Jonas",
    );
    expect(quote.textContent).toBe("Zitat ausblenden (4 Zeilen)");
    expect(quote.getAttribute("aria-expanded")).toBe("true");
    expect(screen.queryByText(/Nordlicht GmbH/)).toBeNull();

    fireEvent.click(quote);
    expect(screen.queryByText(/anbei der Entwurf/)).toBeNull();
  });

  it("opens a folded part that holds a search word, and closes it on request", async () => {
    showText(REPLY, REPLY_SEGMENTS, { words: ["Haftung"], stems: [] });
    expect(await screen.findByText("1 Fundstelle markiert")).toBeTruthy();
    const quote = screen.getByRole("button", { name: "Zitat ausblenden (4 Zeilen, 1 Fundstelle)" });
    expect(screen.getByText("Haftung").tagName).toBe("MARK");
    // The signature holds no hit and stays folded.
    expect(screen.getByRole("button", { name: "Signatur einblenden (3 Zeilen)" })).toBeTruthy();

    fireEvent.click(quote);
    expect(quote.textContent).toBe("Zitat einblenden (4 Zeilen, 1 Fundstelle)");
    expect(screen.queryByText("Haftung")).toBeNull();
    expect(screen.getByText("1 Fundstelle markiert")).toBeTruthy();
  });

  it("shows short quotes between the own words in place, without a toggle", async () => {
    showText(INLINE, INLINE_SEGMENTS);
    const text = await screen.findByText(/Ja, Donnerstag 10 Uhr passt\./);
    expect(text.textContent).toBe(INLINE.trimEnd());
    expect(screen.queryByRole("button")).toBeNull();
    // the quoted lines muted in place, the answers as written
    expect(screen.getByText("> Können wir den Termin auf Donnerstag legen?").tagName).toBe("SPAN");
    expect(text.tagName).toBe("DIV");
  });

  it("opens a forward that is the whole text", async () => {
    showText(FORWARD, [{ kind: "forward", start: 0, end: 217, lines: 6, folded: false }]);
    // shown as the content it is, not muted
    expect((await screen.findByText(/Bitte überweisen Sie den Betrag/)).tagName).toBe("DIV");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts the server's offsets in characters, an emoji as one", async () => {
    showText(EMOJI, [
      { kind: "text", start: 0, end: 21, lines: 1, folded: false },
      { kind: "quote", start: 21, end: 99, lines: 2, folded: true },
    ]);
    expect((await screen.findByText(/Danke/)).textContent).toBe("Danke \u{1F44D}, das passt.");
    fireEvent.click(screen.getByRole("button", { name: "Zitat einblenden (2 Zeilen)" }));
    expect(screen.getByText(/Ist die Haftung/).textContent).toBe(
      "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Ist die Haftung so in Ordnung?",
    );
  });

  it("shows a text without segments as it is", async () => {
    showText("Nur eine Zeile.\n", []);
    expect((await screen.findByText(/Nur eine Zeile/)).textContent).toBe("Nur eine Zeile.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// A reply whose own text and quote end in the same notice, a standard block in 1,234 mails;
// the segments and paragraphs as api/body.py cuts them (tests/api/test_body.py).
const OWN = "Passt so, ich schicke den Vertrag morgen an alle.";
const NOTICE = "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt.";
const HEAD =
  "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Hallo Anna, anbei der Entwurf zur Spende.";
const BLOCKED = `Hallo Jonas,\n\n${OWN}\n\n${NOTICE}\n\n${HEAD}\n>\n> ${NOTICE}\n`;
const NOTICE_HASH = "7198ac121813e610";
const OWN_HASH = "0123456789abcdef";
const HEAD_HASH = "fedcba9876543210";

function blockedText(override: boolean | null = null): MailText {
  const notice = BLOCKED.indexOf(NOTICE);
  const quote = BLOCKED.indexOf("Am 17");
  const quoted = BLOCKED.indexOf(`> ${NOTICE}`);
  const paragraph = (start: number, text: string, hash: string, standard: boolean) => ({
    start,
    end: start + text.length,
    hash,
    standard,
    mails: standard ? 1234 : 0,
    override: hash === OWN_HASH ? override : null,
  });
  return {
    text: BLOCKED,
    truncated: false,
    source: "text/plain",
    has_html: false,
    segments: [
      { kind: "text", start: 0, end: notice, lines: 2, folded: false },
      { kind: "standard", start: notice, end: quote, lines: 1, folded: true, block: NOTICE_HASH },
      { kind: "quote", start: quote, end: quoted, lines: 2, folded: true },
      {
        kind: "standard",
        start: quoted,
        end: BLOCKED.length,
        lines: 1,
        folded: true,
        block: NOTICE_HASH,
      },
    ],
    paragraphs: [
      paragraph(BLOCKED.indexOf(OWN), OWN, OWN_HASH, false),
      paragraph(notice, NOTICE, NOTICE_HASH, true),
      paragraph(quote, HEAD, HEAD_HASH, false),
      paragraph(quoted, `> ${NOTICE}`, NOTICE_HASH, true),
    ],
  };
}

function ownBlock(override: boolean | null): BlockInfo {
  return {
    hash: OWN_HASH,
    sample: OWN,
    standard: false,
    detected: false,
    override,
    pending: override === true,
    mails: 1,
    senders: 1,
    first_date: "2026-10-17T07:12:00Z",
    last_date: "2026-10-17T07:12:00Z",
  };
}

function showBlocked(marks?: SearchMarks, body: MailText = blockedText()) {
  return renderElement(
    <BodyCard mailId={7} tab="text" onTab={() => {}} marks={marks} />,
    (call) => {
      if (call.url.pathname === "/api/mails/7/body") return body;
      if (call.url.pathname === `/api/blocks/${OWN_HASH}/override`) {
        const { standard } = call.body as BlockOverrideUpdate;
        // a choice equal to detection removes the team's choice (api/blocks.py)
        return ownBlock(standard ? true : null);
      }
      return fixtureApi(call);
    },
  );
}

describe("body card, standard blocks", () => {
  it("folds a standard block like a quote, with its mails and a link to its page", async () => {
    showBlocked();
    expect(await screen.findByText(/Passt so, ich schicke/)).toBeTruthy();
    expect(screen.queryByText(new RegExp(NOTICE))).toBeNull();
    const toggle = screen.getByRole("button", { name: "Standardblock einblenden (1 Zeile)" });
    const link = screen.getByRole("link", { name: "in 1.234 Mails" });
    expect(link.getAttribute("href")).toBe(`/ausgeblendet/bloecke/${NOTICE_HASH}`);

    fireEvent.click(toggle);
    expect(screen.getByText(NOTICE).closest("span[class*='quoted']")).toBeTruthy();
    expect(toggle.textContent).toBe("Standardblock ausblenden (1 Zeile)");

    // the quote holds the same block, folded again inside it, and counts its line
    fireEvent.click(screen.getByRole("button", { name: "Zitat einblenden (3 Zeilen)" }));
    expect(screen.getByText(/anbei der Entwurf zur Spende/)).toBeTruthy();
    expect(screen.getAllByText(new RegExp(NOTICE))).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Standardblock einblenden (1 Zeile)" }));
    expect(screen.getByText(`> ${NOTICE}`)).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "in 1.234 Mails" })).toHaveLength(2);
  });

  it("opens a standard block that holds a search word, and the quote around it", async () => {
    showBlocked({ words: ["vertraulich"], stems: [] });
    expect(await screen.findByText("2 Fundstellen markiert")).toBeTruthy();
    // both: the own text's, and the one inside the quote
    expect(
      screen.getAllByRole("button", { name: "Standardblock ausblenden (1 Zeile, 1 Fundstelle)" }),
    ).toHaveLength(2);
    const quote = screen.getByRole("button", {
      name: "Zitat ausblenden (3 Zeilen, 1 Fundstelle)",
    });
    expect(quote.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByText("vertraulich").map((mark) => mark.tagName)).toEqual([
      "MARK",
      "MARK",
    ]);
  });

  it("marks a paragraph from its menu, asking for the editor's name once", async () => {
    const { calls } = showBlocked();
    await screen.findByText(/Passt so, ich schicke/);
    // one handle per paragraph shown: the own text's; the others are folded
    const handle = screen.getByRole("button", { name: "Absatz: Standardblock" });
    expect(handle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(handle);
    const menu = screen.getByRole("group", { name: "Absatz" });
    expect(within(menu).getByText("Wirkt beim nächsten Lauf.")).toBeTruthy();
    fireEvent.click(within(menu).getByRole("button", { name: "Als Standardblock markieren" }));

    const dialog = screen.getByRole("dialog", { name: "Name für Notizen und Änderungen" });
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Lena Vogt" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    expect(
      await screen.findAllByText("Als Standardblock markiert · wirkt beim nächsten Lauf"),
    ).toHaveLength(2); // after the paragraph and in its menu
    const put = calls.filter((call) => call.method === "PUT");
    expect(put.map((call) => [call.url.pathname, call.body])).toEqual([
      [`/api/blocks/${OWN_HASH}/override`, { standard: true, sample: OWN }],
    ]);
    expect(put[0].headers.get("X-Mailrobbe-Editor")).toBe("Lena%20Vogt");

    // taking it back again needs no second question
    fireEvent.click(within(menu).getByRole("button", { name: "Kein Standardblock" }));
    await waitFor(() =>
      expect(
        screen.queryAllByText("Als Standardblock markiert · wirkt beim nächsten Lauf"),
      ).toHaveLength(0),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(calls.filter((call) => call.method === "PUT").map((call) => call.body)).toEqual([
      { standard: true, sample: OWN },
      { standard: false, sample: OWN },
    ]);
  });

  it("shows a pending choice and opens the menu of a standard block inside its fold", async () => {
    localStorage.setItem("mailrobbe.editor", "Lena Vogt");
    showBlocked(undefined, blockedText(true));
    expect(
      await screen.findByText("Als Standardblock markiert · wirkt beim nächsten Lauf"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Standardblock einblenden (1 Zeile)" }));
    const handles = screen.getAllByRole("button", { name: "Absatz: Standardblock" });
    expect(handles).toHaveLength(2);
    fireEvent.click(handles[1]);
    const menu = screen.getByRole("group", { name: "Absatz" });
    expect(within(menu).getByRole("link", { name: "In 1.234 Mails" })).toBeTruthy();
    const back = within(menu).getByRole("button", { name: "Kein Standardblock" });
    // Escape closes the menu and gives the focus back to its handle
    fireEvent.keyDown(back, { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Absatz" })).toBeNull();
    expect(document.activeElement).toBe(handles[1]);
  });
});
