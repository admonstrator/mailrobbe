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
  if (path === "/api/mails") {
    return (url.searchParams.get("q") ?? "").includes("subject:") ? fx.filteredPage : fx.mailPage;
  }
  if (/^\/api\/mails\/\d+\/neighbors$/.test(path)) return fx.neighbors;
  if (/^\/api\/mails\/\d+\/body$/.test(path)) {
    const format = url.searchParams.get("format") ?? "text";
    return { text: fx.mailText, headers: fx.mailHeaders, raw: fx.mailRaw }[format];
  }
  if (method === "GET" && /^\/api\/mails\/\d+$/.test(path)) return fx.mailDetail;
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
