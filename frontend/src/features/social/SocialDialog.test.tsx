import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

async function openDialog(): Promise<HTMLElement> {
  renderApp("/mails/184221");
  fireEvent.click(await screen.findByRole("button", { name: "Als Bild für Soziale Medien" }));
  return await screen.findByRole("dialog");
}

function image(dialog: HTMLElement): HTMLImageElement {
  return within(dialog).getByRole("img", { name: "Vorschau des Bildes" }) as HTMLImageElement;
}

describe("the social media image of a mail (D217)", () => {
  it("shows the picture, what it blacks out and the download", async () => {
    const dialog = await openDialog();
    expect(image(dialog).getAttribute("src")).toBe("/api/mails/184221/social.png?shape=portrait");
    await waitFor(() =>
      expect(dialog.textContent).toContain(
        "9 Stellen geschwärzt: Beteiligte 4, Kontaktdaten 3, Namen im Text 2",
      ),
    );
    const download = within(dialog).getByRole("link", { name: "PNG herunterladen" });
    expect(download.getAttribute("href")).toBe("/api/mails/184221/social.png?shape=portrait");
    expect(download.getAttribute("download")).toBe("mailrobbe-184221-social.png");
    expect(dialog.textContent).toContain("Mailrobbe schwärzt, was es erkennt");
  });

  it("switches a category off and keeps the others, since false is no default", async () => {
    const dialog = await openDialog();
    fireEvent.click(within(dialog).getByLabelText("Beteiligte (Von, An, Cc)"));
    await waitFor(() =>
      expect(image(dialog).getAttribute("src")).toBe(
        "/api/mails/184221/social.png?shape=portrait&participants=false",
      ),
    );
  });

  it("takes the format and the team's own terms into the picture", async () => {
    const dialog = await openDialog();
    fireEvent.click(within(dialog).getByLabelText(/Breitbild/));
    fireEvent.change(within(dialog).getByPlaceholderText(/Projekt Nord/), {
      target: { value: "Projekt Nord, , Aktenzeichen 12/34" },
    });
    await waitFor(() =>
      expect(image(dialog).getAttribute("src")).toBe(
        "/api/mails/184221/social.png?shape=wide&terms=Projekt+Nord&terms=Aktenzeichen+12%2F34",
      ),
    );
  });
});
