import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { createQueryClient } from "../api/queries";
import { routes } from "../routes";
import * as fx from "./fixtures";

export interface ApiCall {
  method: string;
  url: URL;
  body: unknown;
}

const FILTER_KEYS = ["q", "dkim", "sender_domain", "date_from", "date_to", "has_attachment"];

/** Anna Keller and her two aliases, the persons the fixtures have a profile for. */
const ANNA_IDS = [fx.annaProfile.id, ...fx.annaProfile.aliases.map((alias) => alias.person_id)];

const notFound = (what: string) =>
  Response.json({ detail: { code: "not_found", message: `no ${what}` } }, { status: 404 });

/** The person list for q: the fixture page, or the persons whose name or address contain it. */
function personsMatching(q: string): unknown {
  if (!q) return fx.personPage;
  const needle = q.toLowerCase();
  const items = fx.personPage.items.filter((person) =>
    [person.name ?? "", person.email].some((text) => text.toLowerCase().includes(needle)),
  );
  return { items, next_cursor: null, prev_cursor: null, total: items.length };
}

function personApi(method: string, url: URL, id: number, endpoint: string | undefined): unknown {
  if (!ANNA_IDS.includes(id)) return notFound(`person with id ${id}`);
  if (endpoint === undefined && method === "GET") return fx.annaProfile;
  if (endpoint === "/contacts") {
    return url.searchParams.has("cursor") ? fx.contactPage2 : fx.contactPage;
  }
  if (endpoint === "/mail-counts") return fx.personMailCounts;
  if (endpoint === "/unmerge" && method === "POST") {
    const aliases = fx.annaProfile.aliases.filter((alias) => alias.person_id !== id);
    return { ...fx.annaProfile, aliases };
  }
  return notFound("such endpoint");
}

/** The fixture backend: every endpoint the screens use, answered from fixtures.ts. An answer is
 *  a JSON body, or a Response for anything else. */
export function fixtureApi({ method, url }: ApiCall): unknown {
  const path = url.pathname;
  if (path === "/api/stats") return fx.stats;
  if (path === "/api/mbox-files") return fx.mboxFiles;
  if (path === "/api/stats/sender-domains") return fx.stats.sender_domains;
  if (path === "/api/mails/summary") {
    return FILTER_KEYS.some((key) => url.searchParams.has(key))
      ? fx.summaryFiltered
      : fx.summaryAll;
  }
  if (path === "/api/mails" && url.searchParams.has("person")) return fx.personMailPage;
  if (path === "/api/mails") {
    return (url.searchParams.get("q") ?? "").includes("subject:") ? fx.filteredPage : fx.mailPage;
  }
  if (/^\/api\/mails\/\d+\/neighbors$/.test(path)) return fx.neighbors;
  if (/^\/api\/mails\/\d+\/body$/.test(path)) {
    const format = url.searchParams.get("format") ?? "text";
    return { text: fx.mailText, headers: fx.mailHeaders, raw: fx.mailRaw }[format];
  }
  if (method === "GET" && /^\/api\/mails\/\d+$/.test(path)) return fx.mailDetail;
  if (path === "/api/persons") return personsMatching(url.searchParams.get("q") ?? "");
  if (path === "/api/persons/suggestions") {
    return url.searchParams.has("cursor") ? fx.suggestionPage2 : fx.suggestionPage;
  }
  if (path === "/api/persons/suggestions/dismiss") return new Response(null, { status: 204 });
  if (path === "/api/persons/merge") return fx.mergedProfile;
  const person = /^\/api\/persons\/(\d+)(\/[a-z-]+)?$/.exec(path);
  if (person) return personApi(method, url, Number(person[1]), person[2]);
  return Response.json({ detail: "Not Found" }, { status: 404 });
}

/** Renders the app at path against a fake backend; calls records every request. */
export function renderApp(path: string, api: (call: ApiCall) => unknown = fixtureApi) {
  const calls: ApiCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const call: ApiCall = {
        method: init?.method ?? "GET",
        url: new URL(String(input), "http://localhost"),
        body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      };
      calls.push(call);
      const answer = api(call);
      return answer instanceof Response ? answer : Response.json(answer);
    }),
  );
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    queries: { ...queryClient.getDefaultOptions().queries, retry: false },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, calls };
}
