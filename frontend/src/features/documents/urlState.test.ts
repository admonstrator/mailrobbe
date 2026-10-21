import { describe, expect, it } from "vitest";

import { buildQuery } from "../../api/client";
import { listSearch, toListParams } from "../mails/listState";
import {
  DEFAULT_DOCUMENT_LIST_STATE,
  documentListHref,
  documentListSearch,
  documentMailList,
  documentMailsHref,
  facetFilters,
  parseDocumentListState,
  parseDocumentMailState,
  toDocumentFilters,
  toDocumentListParams,
  withDocumentFilters,
  withoutDocumentFilters,
  type DocumentListState,
} from "./urlState";

const parse = (query: string) => parseDocumentListState(new URLSearchParams(query));
const search = (state: DocumentListState) => documentListSearch(state).toString();

const full: DocumentListState = {
  q: '"Konto DE89" Spende',
  name: "liste",
  kind: ["pdf", "spreadsheet"],
  text_status: ["scanned", "encrypted"],
  date_from: "2019-01-01",
  date_to: "2019-12-31",
  person: 11,
  person_role: "received",
  shared: true,
  external: true,
  sort: "mails",
  cursor: "eyJrIjoxfQ",
  page: 3,
};

describe("document list state in the URL", () => {
  it("is the default state for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_DOCUMENT_LIST_STATE);
    expect(search(DEFAULT_DOCUMENT_LIST_STATE)).toBe("");
    expect(documentListHref(DEFAULT_DOCUMENT_LIST_STATE)).toBe("/anhaenge");
  });

  it("survives the round trip with the API's parameter names", () => {
    expect(parse(search(full))).toEqual(full);
    const params = documentListSearch(full);
    expect(params.getAll("kind")).toEqual(["pdf", "spreadsheet"]);
    expect(params.getAll("text_status")).toEqual(["scanned", "encrypted"]);
    expect(params.get("shared")).toBe("true");
    expect([...new Set(params.keys())]).toEqual([
      "q",
      "name",
      "kind",
      "text_status",
      "date_from",
      "date_to",
      "person",
      "person_role",
      "shared",
      "external",
      "sort",
      "cursor",
      "page",
    ]);
  });

  it("ignores values it cannot use and keeps the filter order", () => {
    const state = parse(
      [
        "kind=bogus",
        "kind=spreadsheet",
        "kind=pdf",
        "kind=pdf",
        "text_status=ok",
        "date_from=2019-02-30",
        "person=abc",
        "person_role=sent",
        "sort=relevance",
        "shared=yes",
        "page=4",
      ].join("&"),
    );
    expect(state).toEqual({ ...DEFAULT_DOCUMENT_LIST_STATE, kind: ["pdf", "spreadsheet"] });
  });

  it("keeps a role only together with a person", () => {
    expect(parse("person=11&person_role=sent").person_role).toBe("sent");
    expect(parse("person=11&person_role=cc").person_role).toBeNull();
    expect(toDocumentFilters({ ...DEFAULT_DOCUMENT_LIST_STATE, person_role: "sent" })).toEqual({});
  });

  it("starts again at the first page when a filter changes, and resets the column", () => {
    const next = withDocumentFilters(full, { shared: false });
    expect([next.cursor, next.page, next.shared]).toEqual([null, 1, false]);
    expect(withoutDocumentFilters(full)).toEqual({
      ...DEFAULT_DOCUMENT_LIST_STATE,
      q: full.q,
      sort: "mails",
    });
  });

  it("builds the request without the UI's page and the default sort", () => {
    expect(toDocumentListParams({ ...DEFAULT_DOCUMENT_LIST_STATE, sort: "recent" })).toEqual({});
    const query = buildQuery(toDocumentListParams(full)).toString();
    expect(query).not.toContain("page=");
    expect(query).toBe(search({ ...full, page: 1 }));
  });

  it("counts each checkbox group without its own selection", () => {
    const filters = toDocumentFilters(full);
    expect(facetFilters(filters, "kind")).not.toHaveProperty("kind");
    expect(facetFilters(filters, "kind").text_status).toEqual(["scanned", "encrypted"]);
    expect(facetFilters(filters, "text_status")).not.toHaveProperty("text_status");
    expect(facetFilters({}, "kind")).toEqual({});
  });
});

describe("a document's mails", () => {
  it("are the mail list with document, oldest first, without duplicates", () => {
    const list = documentMailList(5101, { cursor: "c2", page: 2 });
    expect(toListParams(list)).toEqual({
      hide_duplicates: true,
      document: 5101,
      sort: "date_asc",
      cursor: "c2",
    });
    expect(listSearch(list).toString()).toBe(
      "hide_duplicates=true&document=5101&sort=date_asc&cursor=c2&page=2",
    );
    expect(documentMailsHref(5101)).toBe("/mails?hide_duplicates=true&document=5101&sort=date_asc");
  });

  it("keep their page number only with a cursor", () => {
    expect(parseDocumentMailState(new URLSearchParams("page=3"))).toEqual({
      cursor: null,
      page: 1,
    });
    expect(parseDocumentMailState(new URLSearchParams("cursor=x&page=3"))).toEqual({
      cursor: "x",
      page: 3,
    });
  });
});
