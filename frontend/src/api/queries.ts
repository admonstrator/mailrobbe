// Query keys and hooks for every endpoint the screens read or write.

import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  QueryClient,
} from "@tanstack/react-query";

import { ApiError, apiGet, apiPost, apiPut } from "./client";
import type {
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
  Note,
  NoteUpdate,
  Stats,
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
