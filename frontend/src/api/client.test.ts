import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiGet, apiPost, apiPut, buildQuery, withQuery } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(response: Response) {
  const fetch = vi.fn<typeof globalThis.fetch>(async () => response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("buildQuery", () => {
  it("repeats lists, writes true and leaves out empty values and false", () => {
    const query = buildQuery({
      q: "from:anna@ Vertrag",
      dkim: ["pass", "fail"],
      person: [3, 4],
      has_attachment: true,
      flagged: false,
      cursor: null,
      date_from: undefined,
      sender_domain: [],
      sort: "",
      limit: 50,
    });
    expect(query.toString()).toBe(
      "q=from%3Aanna%40+Vertrag&dkim=pass&dkim=fail&person=3&person=4&has_attachment=true&limit=50",
    );
  });

  it("gives a path without question mark when nothing is left", () => {
    expect(withQuery("/api/mails/summary", { q: "", dkim: [] })).toBe("/api/mails/summary");
    expect(withQuery("/api/mails/summary", { q: "x" })).toBe("/api/mails/summary?q=x");
  });
});

describe("requests", () => {
  it("returns the JSON body", async () => {
    const fetch = stubFetch(Response.json({ mails: 3 }));
    await expect(apiGet("/api/stats")).resolves.toEqual({ mails: 3 });
    expect(fetch).toHaveBeenCalledWith("/api/stats", expect.objectContaining({ method: "GET" }));
  });

  it("turns a contract error into ApiError with code, message and status", async () => {
    stubFetch(
      Response.json(
        { detail: { code: "invalid_query", message: "bad term 'after:2026-13-01'" } },
        { status: 400 },
      ),
    );
    const error = await apiGet("/api/mails", { q: "after:2026-13-01" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 400,
      code: "invalid_query",
      message: "bad term 'after:2026-13-01'",
    });
  });

  it("has no code for errors outside the contract", async () => {
    stubFetch(
      Response.json({ detail: [{ loc: ["query", "limit"], msg: "too big" }] }, { status: 422 }),
    );
    await expect(apiGet("/api/mails")).rejects.toMatchObject({ status: 422, code: null });
    stubFetch(new Response("Internal Server Error", { status: 500 }));
    await expect(apiGet("/api/mails")).rejects.toMatchObject({ status: 500, code: null });
  });

  it("sends JSON bodies", async () => {
    const fetch = stubFetch(Response.json({ flagged: true, note: "x", updated_at: null }));
    await apiPut("/api/mails/5/note", { flagged: true, note: "x" });
    const init = fetch.mock.calls[0][1];
    expect(init?.method).toBe("PUT");
    expect(init?.body).toBe('{"flagged":true,"note":"x"}');
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("resolves to undefined for 204 No Content", async () => {
    stubFetch(new Response(null, { status: 204 }));
    await expect(apiPost("/api/persons/suggestions/dismiss", { persons: [1, 2] })).resolves.toBe(
      undefined,
    );
  });
});
