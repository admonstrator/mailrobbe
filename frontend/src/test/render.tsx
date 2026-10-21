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
  const everyone = [...fx.personPage.items, ...fx.personSearch.items];
  const items = [...new Map(everyone.map((person) => [person.id, person])).values()].filter(
    (person) =>
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

/** A document page or its text: the contract PDF and the photo exist. */
function documentApi(id: number, endpoint: string | undefined): unknown {
  const document = [fx.documentDetail, fx.imageDocument].find((candidate) => candidate.id === id);
  if (!document) return notFound(`document with id ${id}`);
  if (endpoint === undefined) return document;
  return document.text_status === "text"
    ? fx.documentText
    : { text: "", truncated: false, text_status: document.text_status };
}

/** The timeline for these parameters: by split, Anna's for a person filter, else the archive. */
function timelineFor(search: URLSearchParams): unknown {
  const split = search.get("split");
  if (split === "person") return fx.timelineByPerson;
  if (split === "thread") return fx.timelineByThread;
  if (split === "term") return fx.timelineByTerm;
  return search.has("person") ? fx.timelineAnna : fx.timelineAll;
}

/** The fixture backend: every endpoint the screens use, answered from fixtures.ts. An answer is
 *  a JSON body, or a Response for anything else. */
export function fixtureApi({ method, url }: ApiCall): unknown {
  const path = url.pathname;
  if (path === "/api/stats") return fx.stats;
  if (path === "/api/research") return fx.research;
  if (path === "/api/research/themes") return fx.themes;
  if (path === "/api/research/starter") return { ...fx.research, starter_missing: 0 };
  if (method === "GET" && /^\/api\/collections\/\d+$/.test(path)) return fx.collectionDetail;
  if (path === "/api/notes") return fx.notePage;
  if (path === "/api/exports" && method === "GET") return fx.exports;
  if (path === "/api/exports") return Response.json(fx.exports[0], { status: 201 });
  if (path.startsWith("/api/permalink/")) return fx.permalink;
  if (path === "/api/mbox-files") return fx.mboxFiles;
  if (path === "/api/stats/sender-domains") return fx.stats.sender_domains;
  if (path === "/api/mails/summary") {
    return FILTER_KEYS.some((key) => url.searchParams.has(key))
      ? fx.summaryFiltered
      : fx.summaryAll;
  }
  if (path === "/api/mails" && url.searchParams.has("document")) return fx.documentMailPage;
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
  if (path === "/api/graph") return fx.graph;
  if (path === "/api/graph/size") return fx.graphSize;
  if (path === "/api/persons") return personsMatching(url.searchParams.get("q") ?? "");
  if (path === "/api/persons/suggestions") {
    return url.searchParams.has("cursor") ? fx.suggestionPage2 : fx.suggestionPage;
  }
  if (path === "/api/persons/suggestions/dismiss") return new Response(null, { status: 204 });
  if (path === "/api/persons/merge") return fx.mergedProfile;
  const person = /^\/api\/persons\/(\d+)(\/[a-z-]+)?$/.exec(path);
  if (person) return personApi(method, url, Number(person[1]), person[2]);
  if (path === "/api/import/status") return fx.importStatus;
  if (path === "/api/import/summary") return fx.importSummary;
  if (path === "/api/import/errors") return fx.importErrorPage(url.searchParams);
  if (path === "/api/import/start")
    return Response.json({ ...fx.importJob, id: 9 }, { status: 202 });
  if (path === "/api/import/pause") return { ...fx.importJob, stop_requested: true };
  if (path === "/api/import/rescan") return fx.scanResult;
  if (path === "/api/dkim/recheck") return Response.json(fx.dkimJobRunning, { status: 202 });
  if (path === "/api/dkim/recheck/stop") return { ...fx.dkimJobRunning, stop_requested: true };
  if (path === "/api/documents") return fx.documentPage;
  if (path === "/api/documents/summary") {
    return url.searchParams.size > 0 ? fx.documentSummaryFiltered : fx.documentSummary;
  }
  if (path === "/api/timeline") return timelineFor(url.searchParams);
  if (path === "/api/timeline/first-mentions") return fx.firstMentions;
  const document = /^\/api\/documents\/(\d+)(\/text)?$/.exec(path);
  if (document) return documentApi(Number(document[1]), document[2]);
  const entities = entityApi(url);
  if (entities !== undefined) return entities;
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

/** The entity endpoints (milestone 10), or undefined for other paths. The facets of a filter are
 *  the filtered fixture whatever the filter; "mehr" gets the kinds it asks for. */
function entityApi(url: URL): unknown {
  const path = url.pathname;
  const search = url.searchParams;
  if (path === "/api/mails/facets") {
    if (search.has("kind")) {
      const kinds = search.getAll("kind");
      const all = { ...fx.entityFacets.kinds, ...fx.entityFacetsAmounts.kinds };
      const asked = Object.entries(all).filter(([kind]) => kinds.includes(kind));
      return { ...fx.entityFacets, kinds: Object.fromEntries(asked) };
    }
    const filtered = [...search.keys()].some((key) => key !== "limit");
    return filtered ? fx.entityFacetsFiltered : fx.entityFacets;
  }
  if (/^\/api\/mails\/\d+\/entities$/.test(path)) return fx.mailEntities;
  if (path === "/api/entities/summary") return fx.entitySummary;
  if (path === "/api/entities/refs") {
    const ids = search.getAll("id").map(Number);
    return Object.values(fx.entities).filter((ref) => ids.includes(ref.id));
  }
  if (path === "/api/entities") return fx.entityPage;
  const detail = /^\/api\/entities\/(\d+)$/.exec(path);
  if (detail) {
    const found = [fx.entityDetail, fx.entityDetailEmail].find(
      (candidate) => candidate.id === Number(detail[1]),
    );
    return found ?? notFound(`entity with id ${detail[1]}`);
  }
  return undefined;
}
