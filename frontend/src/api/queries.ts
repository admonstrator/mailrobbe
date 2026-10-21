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

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut } from "./client";
import type {
  BulkRequest,
  BulkResult,
  CollectionCreate,
  CollectionDetail,
  CollectionInfo,
  CollectionRef,
  CollectionUpdate,
  ContactPage,
  DkimJob,
  DocumentDetail,
  DocumentFilters,
  DocumentListParams,
  DocumentPage,
  DocumentSummary,
  DocumentText,
  DomainCount,
  ExportInfo,
  ExportRequest,
  Graph,
  GraphParams,
  GraphSize,
  ImportErrorPage,
  ImportErrorParams,
  ImportJob,
  ImportStartRequest,
  ImportStatus,
  ImportSummary,
  LinkChange,
  MailDetail,
  MailDkim,
  MailFilters,
  MailHeaders,
  MailListParams,
  MailNeighbors,
  MailOrderParams,
  MailPage,
  MailRaw,
  MailResearch,
  MailSummary,
  MailText,
  Mark,
  MarkUpdate,
  MboxFileInfo,
  MergeRequest,
  NoteInfo,
  NotePage,
  PermalinkTarget,
  PersonListParams,
  PersonMailCountParams,
  PersonMailCounts,
  PersonPage,
  PersonProfile,
  ResearchOverview,
  SavedSearch,
  SavedSearchCreate,
  SavedSearchUpdate,
  ScanResult,
  Stats,
  SuggestionPage,
  TagCreate,
  TagInfo,
  TagRef,
  TagUpdate,
  ThemeInfo,
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
  importStatus: ["import", "status"] as const,
  importSummary: ["import", "summary"] as const,
  importErrors: (params: ImportErrorParams) => ["import", "errors", params] as const,
  importErrorPages: (filters: ImportErrorFilters) => ["import", "error-pages", filters] as const,
  /** Prefix of everything a write to the research file can change, apart from mails. */
  research: ["research"] as const,
  researchOverview: ["research", "overview"] as const,
  collection: (id: number) => ["research", "collection", id] as const,
  notes: (q: string) => ["research", "notes", q] as const,
  exports: ["research", "exports"] as const,
  themes: ["themes"] as const,
  permalink: (hash: string) => ["permalink", hash] as const,
  /** Prefix of everything about documents (D70); an import's attachments phase changes them. */
  documents: ["documents"] as const,
  documentPage: (params: DocumentListParams) => ["documents", "page", params] as const,
  documentSummary: (filters: DocumentFilters) => ["documents", "summary", filters] as const,
  document: (id: number) => ["documents", "detail", id] as const,
  documentText: (id: number) => ["documents", "text", id] as const,
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

// Import dashboard (D46 to D50) -----------------------------------------------------------------

/** The filters of the import errors; pages come with their cursor. */
export type ImportErrorFilters = Pick<ImportErrorParams, "kind" | "mbox_file">;

/** An import or a DKIM run is alive: its process holds the lock of its kind. */
export function runAlive(status: ImportStatus | undefined): boolean {
  return Boolean(status?.import_job?.alive || status?.dkim_job?.alive);
}

/** How often the dashboard asks for the status (D48): every 2 s while a run is alive, else
 *  every 15 s, which also notices a run started on a command line. */
export function importStatusInterval(status: ImportStatus | undefined): number {
  return runAlive(status) ? 2_000 : 15_000;
}

export function useImportStatus() {
  return useQuery({
    queryKey: queryKeys.importStatus,
    queryFn: ({ signal }) => apiGet<ImportStatus>("/api/import/status", undefined, signal),
    refetchInterval: (query) => importStatusInterval(query.state.data),
  });
}

/** The archive figures; most come from global_stats, which change at most every few minutes. */
export function useImportSummary() {
  return useQuery({
    queryKey: queryKeys.importSummary,
    queryFn: ({ signal }) => apiGet<ImportSummary>("/api/import/summary", undefined, signal),
    refetchInterval: 30_000,
  });
}

/** The newest import errors, asked for every 10 s while a run is alive. */
export function useImportErrors(params: ImportErrorParams, alive: boolean) {
  return useQuery({
    queryKey: queryKeys.importErrors(params),
    queryFn: ({ signal }) => apiGet<ImportErrorPage>("/api/import/errors", params, signal),
    refetchInterval: alive ? 10_000 : false,
  });
}

/** Every import error matching the filters, newest first, a page at a time. */
export function useImportErrorPages(filters: ImportErrorFilters) {
  return useInfiniteQuery({
    queryKey: queryKeys.importErrorPages(filters),
    queryFn: ({ pageParam, signal }) =>
      apiGet<ImportErrorPage>("/api/import/errors", { ...filters, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  });
}

/** Puts the run an action returned into the cached status at once, so the buttons follow
 *  before the status is loaded again, which happens right away; so do the header's figures. */
function showRun(
  queryClient: QueryClient,
  run: Partial<Pick<ImportStatus, "import_job" | "dkim_job">>,
) {
  queryClient.setQueryData<ImportStatus>(
    queryKeys.importStatus,
    (status) => status && { ...status, ...run },
  );
  void queryClient.invalidateQueries({ queryKey: queryKeys.importStatus });
  void queryClient.invalidateQueries({ queryKey: queryKeys.stats });
}

export function useStartImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ImportStartRequest) => apiPost<ImportJob>("/api/import/start", request),
    onSuccess: (job) => showRun(queryClient, { import_job: job }),
  });
}

export function usePauseImport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<ImportJob>("/api/import/pause", {}),
    onSuccess: (job) => showRun(queryClient, { import_job: job }),
  });
}

/** Rescans the MBOX directory (D50). A changed file loses its mails at once, so every list and
 *  figure is loaded again. */
export function useRescan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<ScanResult>("/api/import/rescan", {}),
    onSuccess: () => void queryClient.invalidateQueries(),
  });
}

/** Starts the DKIM run of D13: mails not checked yet, no_key and temp_error. */
export function useStartDkimRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<DkimJob>("/api/dkim/recheck", {}),
    onSuccess: (job) => showRun(queryClient, { dkim_job: job }),
  });
}

export function useStopDkimRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<DkimJob>("/api/dkim/recheck/stop", {}),
    onSuccess: (job) => showRun(queryClient, { dkim_job: job }),
  });
}

// Research file (D53 to D64) ------------------------------------------------------------------

/** Tags, Akten, saved searches and counts: the filter column and the Akten screen. */
export function useResearch() {
  return useQuery({
    queryKey: queryKeys.researchOverview,
    queryFn: ({ signal }) => apiGet<ResearchOverview>("/api/research", undefined, signal),
  });
}

/** The themes of themes.toml with their word fields (D64); they change with a new release. */
export function useThemes() {
  return useQuery({
    queryKey: queryKeys.themes,
    queryFn: ({ signal }) => apiGet<ThemeInfo[]>("/api/research/themes", undefined, signal),
    staleTime: Infinity,
  });
}

export function useCollection(id: number) {
  return useQuery({
    queryKey: queryKeys.collection(id),
    queryFn: ({ signal }) => apiGet<CollectionDetail>(`/api/collections/${id}`, undefined, signal),
  });
}

/** Every note, newest first, or those whose text contains q; a page at a time. */
export function useNotes(q: string) {
  return useInfiniteQuery({
    queryKey: queryKeys.notes(q),
    queryFn: ({ pageParam, signal }) =>
      apiGet<NotePage>("/api/notes", { q, cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
  });
}

export function useExports() {
  return useQuery({
    queryKey: queryKeys.exports,
    queryFn: ({ signal }) => apiGet<ExportInfo[]>("/api/exports", undefined, signal),
  });
}

/** The mail a permalink names (D61). */
export function usePermalink(hash: string) {
  return useQuery({
    queryKey: queryKeys.permalink(hash),
    queryFn: ({ signal }) =>
      apiGet<PermalinkTarget>(`/api/permalink/${encodeURIComponent(hash)}`, undefined, signal),
    staleTime: Infinity,
  });
}

/** After any research write: counts and lists are loaded again, and so is every list of mails
 *  (rows show review, tags and notes; filters use them). Byte-identical copies share the data
 *  (D53), so other cached mail details are refreshed when shown again. */
function refreshResearch(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.research });
  void queryClient.invalidateQueries({ queryKey: queryKeys.mails });
  void queryClient.invalidateQueries({ queryKey: ["mail"], refetchType: "none" });
}

/** A research write that answers with something to keep, then refreshes as above. */
function useResearchWrite<V, R>(write: (variables: V) => Promise<R>, keep?: (result: R) => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: write,
    onSuccess: (result) => {
      keep?.(result);
      refreshResearch(queryClient);
    },
  });
}

/** Writes about one mail keep their answer in its cached detail. */
function useMailResearchWrite<V, R>(
  id: number,
  write: (variables: V) => Promise<R>,
  update: (research: MailResearch, result: R, variables: V) => MailResearch,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: write,
    onSuccess: (result, variables) => {
      queryClient.setQueryData<MailDetail>(
        queryKeys.mail(id),
        (mail) => mail && { ...mail, research: update(mail.research, result, variables) },
      );
      refreshResearch(queryClient);
    },
  });
}

export function useSaveMark(mailId: number) {
  return useMailResearchWrite(
    mailId,
    (update: MarkUpdate) => apiPut<Mark>(`/api/mails/${mailId}/mark`, update),
    (research, mark) => ({ ...research, mark }),
  );
}

export function useChangeMailTags(mailId: number) {
  return useMailResearchWrite(
    mailId,
    (change: LinkChange) => apiPost<TagRef[]>(`/api/mails/${mailId}/tags`, change),
    (research, tags) => ({ ...research, tags }),
  );
}

export function useChangeMailCollections(mailId: number) {
  return useMailResearchWrite(
    mailId,
    (change: LinkChange) => apiPost<CollectionRef[]>(`/api/mails/${mailId}/collections`, change),
    (research, collections) => ({ ...research, collections }),
  );
}

export function useAddNote(mailId: number) {
  return useMailResearchWrite(
    mailId,
    (body: string) => apiPost<NoteInfo>(`/api/mails/${mailId}/notes`, { body }),
    (research, note) => ({ ...research, notes: [...research.notes, note] }),
  );
}

export function useEditNote(mailId: number) {
  return useMailResearchWrite(
    mailId,
    ({ id, body }: { id: number; body: string }) =>
      apiPatch<NoteInfo>(`/api/notes/${id}`, { body }),
    (research, note) => ({
      ...research,
      notes: research.notes.map((other) => (other.id === note.id ? note : other)),
    }),
  );
}

export function useDeleteNote(mailId: number) {
  return useMailResearchWrite(
    mailId,
    (id: number) => apiDelete(`/api/notes/${id}`),
    (research, _, id) => ({ ...research, notes: research.notes.filter((note) => note.id !== id) }),
  );
}

export function useBulkChange() {
  return useResearchWrite((request: BulkRequest) =>
    apiPost<BulkResult>("/api/mails/bulk", request),
  );
}

export function useCreateTag() {
  return useResearchWrite((tag: TagCreate) => apiPost<TagInfo>("/api/tags", tag));
}

export function useUpdateTag() {
  return useResearchWrite(({ id, ...update }: TagUpdate & { id: number }) =>
    apiPatch<TagInfo>(`/api/tags/${id}`, update),
  );
}

export function useDeleteTag() {
  return useResearchWrite((id: number) => apiDelete(`/api/tags/${id}`));
}

export function useCreateCollection() {
  return useResearchWrite((collection: CollectionCreate) =>
    apiPost<CollectionInfo>("/api/collections", collection),
  );
}

export function useUpdateCollection() {
  return useResearchWrite(({ id, ...update }: CollectionUpdate & { id: number }) =>
    apiPatch<CollectionInfo>(`/api/collections/${id}`, update),
  );
}

export function useDeleteCollection() {
  return useResearchWrite((id: number) => apiDelete(`/api/collections/${id}`));
}

export function useCreateSearch() {
  return useResearchWrite((search: SavedSearchCreate) =>
    apiPost<SavedSearch>("/api/searches", search),
  );
}

export function useUpdateSearch() {
  return useResearchWrite(({ id, ...update }: SavedSearchUpdate & { id: number }) =>
    apiPatch<SavedSearch>(`/api/searches/${id}`, update),
  );
}

export function useDeleteSearch() {
  return useResearchWrite((id: number) => apiDelete(`/api/searches/${id}`));
}

/** Creates the tags and saved searches of the themes that are still missing (D64). */
export function useCreateStarter() {
  const queryClient = useQueryClient();
  return useResearchWrite(
    () => apiPost<ResearchOverview>("/api/research/starter", {}),
    (overview) => queryClient.setQueryData(queryKeys.researchOverview, overview),
  );
}

/** Records an export (D62); the browser then downloads it from download_url. */
export function useCreateExport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ExportRequest) => apiPost<ExportInfo>("/api/exports", request),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.exports }),
  });
}

// Attachments and documents (D70 to D77) --------------------------------------------------------

export function useDocumentPage(params: DocumentListParams) {
  return useQuery({
    queryKey: queryKeys.documentPage(params),
    queryFn: ({ signal }) => apiGet<DocumentPage>("/api/documents", params, signal),
    placeholderData: keepPreviousData,
  });
}

/** The figures of the filtered document list (D74). The previous ones stay while the next load,
 *  so the counters beside the filters keep their place. */
export function useDocumentSummary(filters: DocumentFilters) {
  return useQuery({
    queryKey: queryKeys.documentSummary(filters),
    queryFn: ({ signal }) => apiGet<DocumentSummary>("/api/documents/summary", filters, signal),
    placeholderData: keepPreviousData,
  });
}

/** A document page (D75); also names the mail list's document filter. */
export function useDocument(id: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.document(id),
    queryFn: ({ signal }) => apiGet<DocumentDetail>(`/api/documents/${id}`, undefined, signal),
    enabled,
  });
}

/** A document's extracted text, up to 400,000 characters, so only loaded when asked for. */
export function useDocumentText(id: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.documentText(id),
    queryFn: ({ signal }) => apiGet<DocumentText>(`/api/documents/${id}/text`, undefined, signal),
    enabled,
  });
}
