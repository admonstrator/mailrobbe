// Query keys and hooks for every endpoint the screens read or write.

import {
  hashKey,
  keepPreviousData,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  QueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { ApiError, apiGet, apiPost, apiPut } from "./client";
import type {
  ContactPage,
  DomainCount,
  Graph,
  GraphParams,
  GraphSize,
  MailDetail,
  MailDkim,
  MailFilters,
  MailHeaders,
  MailListParams,
  MailNeighbors,
  MailOrderParams,
  MailPage,
  MailRaw,
  MailSummary,
  MailText,
  MboxFileInfo,
  MergeRequest,
  Note,
  NoteUpdate,
  PersonListParams,
  PersonMailCountParams,
  PersonMailCounts,
  PersonPage,
  PersonProfile,
  Stats,
  SuggestionPage,
} from "./types";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        // Contract errors (4xx) do not go away by asking again.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status < 500) && failures < 2,
      },
    },
  });
}

export type BodyFormat = "text" | "headers" | "raw";
interface BodyResponse {
  text: MailText;
  headers: MailHeaders;
  raw: MailRaw;
}

export const queryKeys = {
  stats: ["stats"] as const,
  senderDomains: (q: string) => ["stats", "sender-domains", q] as const,
  mboxFiles: ["mbox-files"] as const,
  /** Prefix of everything that depends on the list's contents. */
  mails: ["mails"] as const,
  mailPage: (params: MailListParams) => ["mails", "page", params] as const,
  mailSummary: (filters: MailFilters) => ["mails", "summary", filters] as const,
  neighbors: (id: number, params: MailOrderParams) => ["mails", "neighbors", id, params] as const,
  mail: (id: number) => ["mail", id] as const,
  body: (id: number, format: BodyFormat) => ["mail", id, "body", format] as const,
  /** Prefix of everything a merge, an unmerge or a dismissal can change. */
  persons: ["persons"] as const,
  personPage: (params: PersonListParams) => ["persons", "page", params] as const,
  suggestions: ["persons", "suggestions"] as const,
  person: (id: number) => ["persons", "profile", id] as const,
  contacts: (id: number) => ["persons", "contacts", id] as const,
  personMailCounts: (id: number, params: PersonMailCountParams) =>
    ["persons", "mail-counts", id, params] as const,
  graph: (params: GraphParams) => ["graph", params] as const,
  graphSize: (params: GraphParams) => ["graph-size", params] as const,
};

export function useStats() {
  return useQuery({
    queryKey: queryKeys.stats,
    queryFn: ({ signal }) => apiGet<Stats>("/api/stats", undefined, signal),
    refetchInterval: (query) => (query.state.data?.importer.running ? 10_000 : 60_000),
  });
}

/** Sender domains listed at most by the domain search. */
export const DOMAIN_SEARCH_LIMIT = 100;

export function useSenderDomains(q: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.senderDomains(q),
    queryFn: ({ signal }) =>
      apiGet<DomainCount[]>("/api/stats/sender-domains", { q, limit: DOMAIN_SEARCH_LIMIT }, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useMboxFiles() {
  return useQuery({
    queryKey: queryKeys.mboxFiles,
    queryFn: ({ signal }) => apiGet<MboxFileInfo[]>("/api/mbox-files", undefined, signal),
  });
}

export function useMailPage(params: MailListParams) {
  return useQuery({
    queryKey: queryKeys.mailPage(params),
    queryFn: ({ signal }) => apiGet<MailPage>("/api/mails", params, signal),
    placeholderData: keepPreviousData,
  });
}

export function useMailSummary(filters: MailFilters) {
  return useQuery({
    queryKey: queryKeys.mailSummary(filters),
    queryFn: ({ signal }) => apiGet<MailSummary>("/api/mails/summary", filters, signal),
  });
}

export function useMailNeighbors(id: number, params: MailOrderParams) {
  return useQuery({
    queryKey: queryKeys.neighbors(id, params),
    queryFn: ({ signal }) => apiGet<MailNeighbors>(`/api/mails/${id}/neighbors`, params, signal),
  });
}

export function useMailDetail(id: number) {
  return useQuery({
    queryKey: queryKeys.mail(id),
    queryFn: ({ signal }) => apiGet<MailDetail>(`/api/mails/${id}`, undefined, signal),
  });
}

/** A body view, read from the MBOX file when first asked for; the file does not change. */
export function useMailBody<F extends BodyFormat>(id: number, format: F, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.body(id, format),
    queryFn: ({ signal }) => apiGet<BodyResponse[F]>(`/api/mails/${id}/body`, { format }, signal),
    enabled,
    staleTime: Infinity,
  });
}

export function useRecheckDkim(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<MailDkim>(`/api/mails/${id}/dkim/recheck`),
    onSuccess: (dkim) => {
      queryClient.setQueryData<MailDetail>(queryKeys.mail(id), (mail) => mail && { ...mail, dkim });
      void queryClient.invalidateQueries({ queryKey: queryKeys.mails, refetchType: "none" });
    },
  });
}

export function useSaveNote(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: NoteUpdate) => apiPut<Note>(`/api/mails/${id}/note`, update),
    onSuccess: (note) => {
      queryClient.setQueryData<MailDetail>(queryKeys.mail(id), (mail) => mail && { ...mail, note });
      // The list shows flags and filters by them; refresh it when it is shown again.
      void queryClient.invalidateQueries({ queryKey: queryKeys.mails, refetchType: "none" });
    },
  });
}

export function usePersonPage(params: PersonListParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.personPage(params),
    queryFn: ({ signal }) => apiGet<PersonPage>("/api/persons", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** The open alias suggestions, a page at a time ("Weitere laden"). */
export function useSuggestions() {
  return useInfiniteQuery({
    queryKey: queryKeys.suggestions,
    queryFn: ({ pageParam, signal }) =>
      apiGet<SuggestionPage>("/api/persons/suggestions", { cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

/** A profile. Asked for an alias, the backend answers with its root, which is then cached under
 *  the root's id as well, for the page that replaces the alias's URL. */
export function usePerson(id: number) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: queryKeys.person(id),
    queryFn: async ({ signal }) => {
      const profile = await apiGet<PersonProfile>(`/api/persons/${id}`, undefined, signal);
      if (profile.id !== id) queryClient.setQueryData(queryKeys.person(profile.id), profile);
      return profile;
    },
  });
}

/** All contacts of a person, a page at a time. */
export function useContacts(id: number) {
  return useInfiniteQuery({
    queryKey: queryKeys.contacts(id),
    queryFn: ({ pageParam, signal }) =>
      apiGet<ContactPage>(`/api/persons/${id}/contacts`, { cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

export function usePersonMailCounts(id: number, params: PersonMailCountParams, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.personMailCounts(id, params),
    queryFn: ({ signal }) =>
      apiGet<PersonMailCounts>(`/api/persons/${id}/mail-counts`, params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** Removes the suggestion of persons a and b from the cached list right away, so its row goes
 *  before the list is loaded again. */
function dropSuggestion(queryClient: QueryClient, a: number, b: number) {
  const pair = (x: number, y: number) => (x === a && y === b) || (x === b && y === a);
  queryClient.setQueryData<InfiniteData<SuggestionPage>>(queryKeys.suggestions, (data) => {
    if (!data) return data;
    const found = data.pages.some((page) =>
      page.items.some((item) => pair(item.first.id, item.second.id)),
    );
    if (!found) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.filter((item) => !pair(item.first.id, item.second.id)),
        total: Math.max(0, page.total - 1),
      })),
    };
  });
}

/** After a merge or unmerge: the profile the backend returned, and everything else about
 *  persons and mails loaded again, since figures, lists and the person filter change. */
function refreshPersons(queryClient: QueryClient, profile: PersonProfile) {
  queryClient.setQueryData(queryKeys.person(profile.id), profile);
  const kept = hashKey(queryKeys.person(profile.id));
  void queryClient.invalidateQueries({
    queryKey: queryKeys.persons,
    predicate: (query) => query.queryHash !== kept,
  });
  void queryClient.invalidateQueries({ queryKey: queryKeys.mails });
  void queryClient.invalidateQueries({ queryKey: queryKeys.stats });
  // The detail's participant figures are those of the roots (D28).
  void queryClient.invalidateQueries({ queryKey: ["mail"], refetchType: "none" });
}

export function useMergePersons() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: MergeRequest) => apiPost<PersonProfile>("/api/persons/merge", request),
    onSuccess: (profile, request) => {
      for (const source of request.sources) dropSuggestion(queryClient, request.target, source);
      refreshPersons(queryClient, profile);
    },
  });
}

/** Unmerges an alias (its own person id); the answer is the profile of its former root. */
export function useUnmergePerson() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (aliasId: number) => apiPost<PersonProfile>(`/api/persons/${aliasId}/unmerge`),
    onSuccess: (profile) => refreshPersons(queryClient, profile),
  });
}

export function useDismissSuggestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (persons: [number, number]) =>
      apiPost<void>("/api/persons/suggestions/dismiss", { persons }),
    onSuccess: (_, [a, b]) => {
      dropSuggestion(queryClient, a, b);
      // The other lists show the suggestion too: the profiles of both and the count.
      void queryClient.invalidateQueries({ queryKey: queryKeys.persons });
    },
  });
}

/** One excerpt of the map; also for prefetching the next year of the playback. */
export function graphQuery(params: GraphParams) {
  return queryOptions({
    queryKey: queryKeys.graph(params),
    queryFn: ({ signal }) => apiGet<Graph>("/api/graph", params, signal),
  });
}

/** The map for params, the previous one staying while the next loads; null loads nothing. */
export function useGraph(params: GraphParams | null) {
  return useQuery({
    ...graphQuery(params ?? {}),
    enabled: params !== null,
    placeholderData: keepPreviousData,
  });
}

/** The size the map for params would have. A changed draft drops the running request. */
export function useGraphSize(params: GraphParams | null) {
  return useQuery({
    queryKey: queryKeys.graphSize(params ?? {}),
    queryFn: ({ signal }) => apiGet<GraphSize>("/api/graph/size", params ?? {}, signal),
    enabled: params !== null,
    placeholderData: keepPreviousData,
  });
}
