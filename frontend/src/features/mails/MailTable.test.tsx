import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailItems } from "../../test/fixtures";
import { renderElement } from "../../test/render";
import { MailTable } from "./MailTable";

const COLUMNS = { to: true, attachment: true, size: false, mbox: false };

describe("mail table", () => {
  it("marks the mails with near duplicates by how many others their group has", () => {
    const [first, second, third] = mailItems;
    renderElement(
      <MailTable
        items={[{ ...first, near_count: 2 }, { ...second, near_count: 1 }, third]}
        columns={COLUMNS}
        detailSearch=""
        mboxPath={() => "export.mbox"}
        stale={false}
      />,
    );
    const rows = screen.getAllByRole("row").slice(1);
    const two = within(rows[0]).getByRole("img", { name: "2 weitere nahezu gleiche Mails" });
    expect([two.textContent, two.title]).toEqual(["+2", "2 weitere nahezu gleiche Mails"]);
    expect(
      within(rows[1]).getByRole("img", { name: "1 weitere nahezu gleiche Mail" }).textContent,
    ).toBe("+1");
    expect(within(rows[2]).queryByRole("img", { name: /nahezu gleiche/ })).toBeNull();
  });
});
