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

import {
  ApiError,
  apiDelete,
  apiFetch,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  attachmentHtmlUrl,
  socialPath,
  socialQuery,
  type SocialTarget,
} from "./client";
import { useDebounced } from "../lib/useDebounced";
import { ENTITY_REFS_LIMIT } from "./types";
import type {
  AiAliasRun,
  AiChanged,
  AiFacets,
  AiJob,
  AiQueued,
  AiQueueRequest,
  AiResultPage,
  AiResultParams,
  AiRunRequest,
  AiSendLogPage,
  AiStatus,
  AiSummaryParams,
  AiSummaryView,
  AiTagAdopt,
  AiTagAdopted,
  AiTagCount,
  AiTagParams,
  AiTaskAction,
  AiTaskPage,
  AiTaskParams,
  AttachmentInfo,
  BlockDetail,
  BlockInfo,
  BlockListParams,
  BlockOverrideUpdate,
  BlockPage,
  BlockSummary,
  BulkRequest,
  BulkResult,
  CertainMergePlan,
  CertainMergeResult,
  CollectionCreate,
  CollectionDetail,
  CollectionInfo,
  CollectionRef,
  CollectionUpdate,
  ContactPage,
  DkimJob,
  DkimKeysJob,
  DkimKeysRunRequest,
  DocumentDetail,
  DocumentFilters,
  DocumentListParams,
  DocumentPage,
  DocumentSummary,
  DocumentText,
  DomainCount,
  EventPlaces,
  EntityDetail,
  EntityFacetParams,
  EntityFacets,
  EntityListParams,
  EntityPage,
  EntityRef,
  EntitySummary,
  ExportInfo,
  ExportRequest,
  FirstMentionParams,
  FirstMentions,
  Graph,
  GraphParams,
  GraphSize,
  HideRuleFields,
  HideRuleInfo,
  HideRuleList,
  HideRulePreview,
  HideRuleUpdate,
  HideSuggestion,
  ImportErrorPage,
  ImportErrorParams,
  ImportJob,
  ImportStartRequest,
  ImportStatus,
  ImportSummary,
  KeyArchivePreview,
  LinkChange,
  MailDetail,
  MailDkim,
  MailEntity,
  MailFilters,
  MailHeaders,
  MailListParams,
  MailNeighbors,
  MailOrderParams,
  MailPage,
  MailRaw,
  MailResearch,
  MailSummary,
  MailHits,
  MailHitsParams,
  MailSignals,
  MailText,
  ManualKeyRequest,
  MapDownloadRequest,
  MapJob,
  MapStatus,
  Mark,
  MarkUpdate,
  MboxFileInfo,
  MergeLogPage,
  MergeRequest,
  MergeUndoResult,
  MetadataValueParams,
  MetadataValues,
  NoteInfo,
  NotePage,
  PasswordTry,
  PasswordTryResult,
  PermalinkTarget,
  PersonEvents,
  PersonLabelUpdate,
  PersonListParams,
  PersonMailCountParams,
  PersonMailCounts,
  PersonPage,
  PersonProfile,
  PersonSignals,
  PhotoDetail,
  PhotoList,
  PhotoListParams,
  PhotoPoints,
  PlaceParams,
  PlaceSummary,
  ResearchOverview,
  SavedSearch,
  SavedSearchCreate,
  SavedSearchUpdate,
  ScanResult,
  SelectorDetail,
  SelectorListParams,
  SelectorPage,
  SelectorSummary,
  ServiceCheck,
  SettingsUpdate,
  SettingsView,
  SignalFacets,
  SignalOverview,
  SocialCard,
  Stats,
  SuggestionPage,
  SuggestionView,
  TagCreate,
  TagInfo,
  TagRef,
  TagUpdate,
  TextPlaces,
  ThemeInfo,
  Timeline,
  TimelineParams,
  TopicClusters,
  TopicPeriodParams,
  TopicPeriods,
  TopicTermParams,
  TopicTerms,
  TownLabel,
  TranscriptSocialParams,
  TranscriptView,
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
  socialCard: (target: SocialTarget, params: TranscriptSocialParams) =>
    ["social", target, params] as const,
  /** Prefix of everything a merge, an unmerge or a dismissal can change. */
  persons: ["persons"] as const,
  personPage: (params: PersonListParams) => ["persons", "page", params] as const,
  suggestions: ["persons", "suggestions"] as const,
  person: (id: number) => ["persons", "profile", id] as const,
  contacts: (id: number) => ["persons", "contacts", id] as const,
  personMailCounts: (id: number, params: PersonMailCountParams) =>
    ["persons", "mail-counts", id, params] as const,
  personEvents: (id: number) => ["persons", "events", id] as const,
  certainMergePlan: ["persons", "merge-certain"] as const,
  mergeLog: ["persons", "merges"] as const,
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
  /** A document's transcript lines (D296), by the result they belong to (null: the valid one). */
  documentTranscript: (id: number, result: number | null) =>
    ["documents", "transcript", id, result] as const,
  hits: (id: number, params: MailHitsParams) => ["documents", "hits", id, params] as const,
  metadataValues: (params: MetadataValueParams) => ["documents", "metadata", params] as const,
  attachmentHtml: (id: number) => ["attachments", "html", id] as const,
  /** Prefix of everything about keys of deleted selectors (D100 to D104). */
  keys: ["keys"] as const,
  selectorSummary: ["keys", "summary"] as const,
  selectorPage: (params: SelectorListParams) => ["keys", "page", params] as const,
  selector: (name: string) => ["keys", "selector", name] as const,
  archivePreview: ["keys", "archive-preview"] as const,
  timeline: (params: TimelineParams) => ["mails", "timeline", params] as const,
  firstMentions: (params: FirstMentionParams) => ["mails", "first-mentions", params] as const,
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

export function useMailDetail(id: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.mail(id),
    queryFn: ({ signal }) => apiGet<MailDetail>(`/api/mails/${id}`, undefined, signal),
    enabled,
    // asked again while an attachment's text recognition or transcription is queued or running
    // (D280, D295)
    refetchInterval: (query) => (aiQueued(query.state.data?.attachments) ? OCR_POLL : false),
  });
}

/** How often a page asks again while a text recognition or a transcription it shows is queued
 *  or running. */
export const OCR_POLL = 3_000;

function aiQueued(attachments: AttachmentInfo[] | undefined): boolean {
  return (attachments ?? []).some(
    (attachment) =>
      attachment.ocr === "queued" ||
      attachment.transcript === "queued" ||
      aiQueued(attachment.members),
  );
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

/** What the social media picture of these parameters blacks out (D217, D298), beside its
 *  preview. */
export function useSocialCard(target: SocialTarget, params: TranscriptSocialParams) {
  return useQuery({
    queryKey: queryKeys.socialCard(target, params),
    queryFn: ({ signal }) =>
      apiGet<SocialCard>(socialPath(target), socialQuery(target, params), signal),
    placeholderData: keepPreviousData,
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

/** The open alias suggestions of a view, a page at a time ("Weitere laden"); asked again every
 *  5 s while the alias check runs, so its verdicts show as they come. */
export function useSuggestions(view: SuggestionView = "certain") {
  return useInfiniteQuery({
    queryKey: [...queryKeys.suggestions, view],
    queryFn: ({ pageParam, signal }) =>
      apiGet<SuggestionPage>(
        "/api/persons/suggestions",
        view === "ai" ? { cursor: pageParam, ai: true } : { cursor: pageParam, tier: view },
        signal,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    refetchInterval: (query) => (query.state.data?.pages[0]?.check.running ? 5000 : false),
  });
}

/** "Mit KI prüfen" (D321): starts `mailrobbe ai run --aliases`. */
export function useStartAliasCheck() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<AiAliasRun>("/api/ai/run/aliases", {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions });
      void queryClient.invalidateQueries({ queryKey: aiKeys.status });
    },
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

/** Removes the suggestion of persons a and b from the cached lists right away, so its row goes
 *  before the list is loaded again. */
function dropSuggestion(queryClient: QueryClient, a: number, b: number) {
  const pair = (x: number, y: number) => (x === a && y === b) || (x === b && y === a);
  queryClient.setQueriesData<InfiniteData<SuggestionPage>>(
    { queryKey: queryKeys.suggestions },
    (data) => {
      if (!data) return data;
      const found = data.pages
        .flatMap((page) => page.items)
        .find((item) => pair(item.first.id, item.second.id));
      if (!found) return data;
      return {
        ...data,
        pages: data.pages.map((page) => ({
          ...page,
          items: page.items.filter((item) => !pair(item.first.id, item.second.id)),
          total: Math.max(0, page.total - 1),
          counts: { ...page.counts, [found.tier]: Math.max(0, page.counts[found.tier] - 1) },
        })),
      };
    },
  );
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

/** The calendar events a person organised or was invited to (D155). */
export function usePersonEvents(id: number) {
  return useQuery({
    queryKey: queryKeys.personEvents(id),
    queryFn: ({ signal }) => apiGet<PersonEvents>(`/api/persons/${id}/events`, undefined, signal),
  });
}

/** Names a person's address (D156); blank fields remove the label. Names show everywhere, so
 *  lists, mails and the map load again. */
export function useSaveLabel(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: PersonLabelUpdate) =>
      apiPut<PersonProfile>(`/api/persons/${id}/label`, update),
    onSuccess: (profile) => {
      refreshPersons(queryClient, profile);
      void queryClient.invalidateQueries({ queryKey: ["graph"] });
    },
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

/** After merges, or undoing them, with no one profile to show: everything about persons and
 *  mails loaded again, as refreshPersons does. */
function refreshMerged(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.persons });
  void queryClient.invalidateQueries({ queryKey: queryKeys.mails });
  void queryClient.invalidateQueries({ queryKey: queryKeys.stats });
  void queryClient.invalidateQueries({ queryKey: ["mail"], refetchType: "none" });
}

/** What "Alle sicheren zusammenführen" would merge now (D162), asked when its dialog opens. */
export function useCertainMergePlan(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.certainMergePlan,
    queryFn: ({ signal }) =>
      apiGet<CertainMergePlan>("/api/persons/merge-certain", undefined, signal),
    enabled,
    staleTime: 0,
  });
}

/** Merges every certain suggestion as one run (D162). */
export function useMergeCertain() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<CertainMergeResult>("/api/persons/merge-certain"),
    onSuccess: () => refreshMerged(queryClient),
  });
}

/** The merge log (D163), newest first, a page at a time. */
export function useMergeLog() {
  return useInfiniteQuery({
    queryKey: queryKeys.mergeLog,
    queryFn: ({ pageParam, signal }) =>
      apiGet<MergeLogPage>("/api/persons/merges", { cursor: pageParam }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

/** Undoes one logged merge (D163). */
export function useUndoMerge() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mergeId: number) =>
      apiPost<MergeUndoResult>(`/api/persons/merges/${mergeId}/undo`),
    onSuccess: () => refreshMerged(queryClient),
  });
}

/** Undoes every merge of a run of "Alle sicheren zusammenführen" not undone yet (D162). */
export function useUndoMergeBatch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (batchId: number) =>
      apiPost<MergeUndoResult>(`/api/persons/merge-batches/${batchId}/undo`),
    onSuccess: () => refreshMerged(queryClient),
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
  return Boolean(
    status?.import_job?.alive ||
    status?.dkim_job?.alive ||
    status?.keys_job?.alive ||
    status?.ai_job?.alive,
  );
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
  run: Partial<Pick<ImportStatus, "import_job" | "dkim_job" | "keys_job">>,
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
    // asked again while its text recognition or transcription is queued or running, so the
    // result shows (D280, D296)
    refetchInterval: (query) =>
      query.state.data?.ai?.task || query.state.data?.transcript?.task ? OCR_POLL : false,
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

/** A recording's transcript with its lines (D296), by its result: the document page names the
 *  one it shows, so a new transcript is loaded once the page learns of it; the mail's preview
 *  asks for the valid one (result null). */
export function useDocumentTranscript(id: number, enabled: boolean, result: number | null = null) {
  return useQuery({
    queryKey: queryKeys.documentTranscript(id, result),
    queryFn: ({ signal }) =>
      apiGet<TranscriptView>(`/api/documents/${id}/transcript`, undefined, signal),
    enabled,
  });
}

/** Where the mail list's full text words occur in one mail (D79), in the list's places and as
 *  whole words when it searched for them (D176); under the documents prefix, so an import's new
 *  texts refresh it. */
export function useMailHits(id: number, params: MailHitsParams) {
  return useQuery({
    queryKey: queryKeys.hits(id, params),
    queryFn: ({ signal }) => apiGet<MailHits>(`/api/mails/${id}/hits`, params, signal),
    enabled: (params.q ?? "").trim() !== "",
  });
}

/** A DOCX or ODT as sanitized HTML (D122), converted on the first request. Dropped once its
 *  preview closes: it may hold large images, and the server keeps the conversion. */
export function useAttachmentHtml(id: number) {
  return useQuery({
    queryKey: queryKeys.attachmentHtml(id),
    queryFn: ({ signal }) =>
      apiFetch(attachmentHtmlUrl(id), signal).then((answer) => answer.text()),
    staleTime: Infinity,
    gcTime: 0,
  });
}

/** The authors or programs of the filtered documents whose value holds the search (D167), for
 *  the search within a facet of the document list. */
export function useMetadataValues(params: MetadataValueParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.metadataValues(params),
    queryFn: ({ signal }) =>
      apiGet<MetadataValues>("/api/documents/metadata-values", params, signal),
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Tries a typed-in password (D237) on one locked document, or with document null on every
 *  locked one, which can take a minute. What it opens is extracted at once, so everything about
 *  documents is loaded again, and the mail details, whose attachments show the protection, when
 *  shown again. A document opened meanwhile (not_locked) is loaded again to show how it stands. */
export function useTryPassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ document, password }: { document: number | null; password: string }) =>
      apiPost<PasswordTryResult>(
        document === null ? "/api/documents/passwords" : `/api/documents/${document}/password`,
        { password } satisfies PasswordTry,
      ),
    onSuccess: (result) => {
      if (result.opened.length === 0) return;
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      void queryClient.invalidateQueries({ queryKey: ["mail"], refetchType: "none" });
    },
    onError: (error, { document }) => {
      if (document !== null && error instanceof ApiError && error.code === "not_locked") {
        void queryClient.invalidateQueries({ queryKey: queryKeys.document(document) });
      }
    },
  });
}

// Keys of deleted selectors (D100 to D104) ------------------------------------------------------

const selectorUrl = (name: string) => `/api/dkim/selectors/${encodeURIComponent(name)}`;

/** The import status as the key screens read it: every 2 s while a dkim-keys run is alive (the
 *  dashboard's own polling does not count it), otherwise not again; on the dashboard its own
 *  polling notices a run started elsewhere. */
export function useKeysStatus() {
  return useQuery({
    queryKey: queryKeys.importStatus,
    queryFn: ({ signal }) => apiGet<ImportStatus>("/api/import/status", undefined, signal),
    refetchInterval: (query) => (query.state.data?.keys_job?.alive ? 2_000 : false),
  });
}

/** The figures of the card "Gelöschte Selektoren"; a run's end loads them again. */
export function useSelectorSummary() {
  return useQuery({
    queryKey: queryKeys.selectorSummary,
    queryFn: ({ signal }) =>
      apiGet<SelectorSummary>("/api/dkim/selectors/summary", undefined, signal),
  });
}

export function useSelectorPage(params: SelectorListParams) {
  return useQuery({
    queryKey: queryKeys.selectorPage(params),
    queryFn: ({ signal }) => apiGet<SelectorPage>("/api/dkim/selectors", params, signal),
    placeholderData: keepPreviousData,
  });
}

/** One key name with its keys, their evidence, the lookups and its latest mails. */
export function useSelector(name: string) {
  return useQuery({
    queryKey: queryKeys.selector(name),
    queryFn: ({ signal }) => apiGet<SelectorDetail>(selectorUrl(name), undefined, signal),
  });
}

/** What a fetch from the key archive would send (D102), asked anew each time it is shown. */
export function useArchivePreview() {
  return useQuery({
    queryKey: queryKeys.archivePreview,
    queryFn: ({ signal }) =>
      apiGet<KeyArchivePreview>("/api/dkim/archive/preview", undefined, signal),
    staleTime: 0,
  });
}

/** Adds a key found elsewhere (D103). The answer is the name's page with the key; the backend
 *  then checks the name's mails in a run of its own, so the figures follow its end. */
export function useAddManualKey(name: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ManualKeyRequest) =>
      apiPost<SelectorDetail>(`${selectorUrl(name)}/keys`, request),
    onSuccess: (detail) => {
      queryClient.setQueryData(queryKeys.selector(name), detail);
      const kept = hashKey(queryKeys.selector(name));
      void queryClient.invalidateQueries({
        queryKey: queryKeys.keys,
        predicate: (query) => query.queryHash !== kept,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.importStatus });
    },
  });
}

/** Starts a dkim-keys run (D101): reconstruct, search, fetch or check. */
export function useStartKeysRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: DkimKeysRunRequest) =>
      apiPost<DkimKeysJob>("/api/dkim/keys/run", request),
    onSuccess: (job) => showRun(queryClient, { keys_job: job }),
  });
}

export function useStopKeysRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<DkimKeysJob>("/api/dkim/keys/run/stop", {}),
    onSuccess: (job) => showRun(queryClient, { keys_job: job }),
  });
}

// Timeline (D90 to D94) -------------------------------------------------------------------------

/** The matching mails over time; under the mails prefix, so research writes refresh it. The
 *  previous one stays while the next loads, so the chart keeps its place. */
export function useTimeline(params: TimelineParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.timeline(params),
    queryFn: ({ signal }) => apiGet<Timeline>("/api/timeline", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useFirstMentions(params: FirstMentionParams, enabled = true) {
  return useQuery({
    queryKey: queryKeys.firstMentions(params),
    queryFn: ({ signal }) => apiGet<FirstMentions>("/api/timeline/first-mentions", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

// Entities (D80 to D89) -------------------------------------------------------------------------

export const entityKeys = {
  /** Prefix of everything about entities; an import's entities phase changes them. */
  entities: ["entities"] as const,
  page: (params: EntityListParams) => ["entities", "page", params] as const,
  summary: ["entities", "summary"] as const,
  refs: (ids: number[]) => ["entities", "refs", ids] as const,
  detail: (id: number) => ["entities", "detail", id] as const,
  /** Under the mail list's prefix: the facets count the mails of a filter (D87), so whatever
   *  changes the list's contents changes them. */
  facets: (params: EntityFacetParams) => ["mails", "facets", params] as const,
  mail: (id: number) => ["mail", id, "entities"] as const,
};

/** The top entities of the mail list's filters (D87), in a query of its own, so the list never
 *  waits for them; the previous ones stay while the next load. */
export function useEntityFacets(params: EntityFacetParams, enabled = true) {
  return useQuery({
    queryKey: entityKeys.facets(params),
    queryFn: ({ signal }) => apiGet<EntityFacets>("/api/mails/facets", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** Entities per kind and the texts not scanned yet. */
export function useEntitySummary(enabled = true) {
  return useQuery({
    queryKey: entityKeys.summary,
    queryFn: ({ signal }) => apiGet<EntitySummary>("/api/entities/summary", undefined, signal),
    enabled,
  });
}

/** Label and kind of the entities of a filter, for its chips: one request for all ids, sorted
 *  so that the same ids share it. The names stay while those of a changed filter load. */
export function useEntityRefs(ids: number[]) {
  const sorted = [...ids].sort((a, b) => a - b).slice(0, ENTITY_REFS_LIMIT);
  return useQuery({
    queryKey: entityKeys.refs(sorted),
    queryFn: ({ signal }) => apiGet<EntityRef[]>("/api/entities/refs", { id: sorted }, signal),
    enabled: sorted.length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
  });
}

export function useEntityPage(params: EntityListParams) {
  return useQuery({
    queryKey: entityKeys.page(params),
    queryFn: ({ signal }) => apiGet<EntityPage>("/api/entities", params, signal),
    placeholderData: keepPreviousData,
  });
}

/** An entity page (D88). */
export function useEntity(id: number) {
  return useQuery({
    queryKey: entityKeys.detail(id),
    queryFn: ({ signal }) => apiGet<EntityDetail>(`/api/entities/${id}`, undefined, signal),
  });
}

/** What was found in one mail and its attachments (D89). */
export function useMailEntities(id: number) {
  return useQuery({
    queryKey: entityKeys.mail(id),
    queryFn: ({ signal }) => apiGet<MailEntity[]>(`/api/mails/${id}/entities`, undefined, signal),
  });
}

// Topics (D140 to D148) -------------------------------------------------------------------------

export const topicKeys = {
  /** Prefix of what the topics phase stores; an import computes it again (D146). */
  topics: ["topics"] as const,
  periods: (params: TopicPeriodParams) => ["topics", "periods", params] as const,
  clusters: ["topics", "clusters"] as const,
  /** Under the mail list's prefix: the terms of a selection count the mails of a filter
   *  (D144), so whatever changes the list's contents changes them. */
  terms: (params: TopicTermParams) => ["mails", "topic-terms", params] as const,
};

/** The terms per month, quarter or year as the topics phase stored them (D143); the previous
 *  unit stays while the next loads. */
export function useTopicPeriods(params: TopicPeriodParams, enabled = true) {
  return useQuery({
    queryKey: topicKeys.periods(params),
    queryFn: ({ signal }) => apiGet<TopicPeriods>("/api/topics/periods", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** The terms of the mails of the mail list's filters, counted on request (D144); the previous
 *  ones stay while the next are counted. */
export function useTopicTerms(params: TopicTermParams, enabled = true) {
  return useQuery({
    queryKey: topicKeys.terms(params),
    queryFn: ({ signal }) => apiGet<TopicTerms>("/api/topics/terms", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** The clusters of terms that stand together across the archive (D145). */
export function useTopicClusters(enabled = true) {
  return useQuery({
    queryKey: topicKeys.clusters,
    queryFn: ({ signal }) => apiGet<TopicClusters>("/api/topics/clusters", undefined, signal),
    enabled,
  });
}

// Signals (D130 to D139) ------------------------------------------------------------------------

export const signalKeys = {
  /** The overview /auffaelligkeiten; an import's signals phase changes it. */
  overview: ["signals"] as const,
  /** Under the mail list's prefix, as the entity facets: whatever changes the list's contents
   *  changes them. */
  facets: (filters: MailFilters) => ["mails", "signals", filters] as const,
  mail: (id: number) => ["mail", id, "signals"] as const,
  /** Under the persons prefix: a merge changes them, and they are counted on request. */
  person: (id: number) => ["persons", "signals", id] as const,
};

/** The figures, rules and persons fallen silent of the last signals phase (D137). */
export function useSignals(enabled = true) {
  return useQuery({
    queryKey: signalKeys.overview,
    queryFn: ({ signal }) => apiGet<SignalOverview>("/api/signals", undefined, signal),
    enabled,
  });
}

/** Mails per signal among the mail list's (D136), in a query of its own, so the list never
 *  waits for them; the previous ones stay while the next load. */
export function useSignalFacets(filters: MailFilters, enabled = true) {
  return useQuery({
    queryKey: signalKeys.facets(filters),
    queryFn: ({ signal }) => apiGet<SignalFacets>("/api/mails/signals", filters, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** The signals of one mail and what makes each hold. */
export function useMailSignals(id: number) {
  return useQuery({
    queryKey: signalKeys.mail(id),
    queryFn: ({ signal }) => apiGet<MailSignals>(`/api/mails/${id}/signals`, undefined, signal),
  });
}

/** The signals of a person's sent mails and whether it fell silent; of the root for an alias. */
export function usePersonSignals(id: number) {
  return useQuery({
    queryKey: signalKeys.person(id),
    queryFn: ({ signal }) => apiGet<PersonSignals>(`/api/persons/${id}/signals`, undefined, signal),
  });
}

// Standard blocks (D224 to D227) ----------------------------------------------------------------

export const blockKeys = {
  /** Prefix of everything a choice of the team or a blocks step changes. */
  all: ["blocks"] as const,
  summary: ["blocks", "summary"] as const,
  page: (params: BlockListParams) => ["blocks", "page", params] as const,
  detail: (hash: string) => ["blocks", "detail", hash] as const,
};

/** The figures of the last blocks step and the choices the next run applies. */
export function useBlockSummary() {
  return useQuery({
    queryKey: blockKeys.summary,
    queryFn: ({ signal }) => apiGet<BlockSummary>("/api/blocks/summary", undefined, signal),
  });
}

/** One page of the standard blocks or of those taken back; the previous page stays while the
 *  next loads. */
export function useBlockPage(params: BlockListParams) {
  return useQuery({
    queryKey: blockKeys.page(params),
    queryFn: ({ signal }) => apiGet<BlockPage>("/api/blocks", params, signal),
    placeholderData: keepPreviousData,
  });
}

/** A block with its senders and domains, counted on request. */
export function useBlock(hash: string, enabled = true) {
  return useQuery({
    queryKey: blockKeys.detail(hash),
    queryFn: ({ signal }) => apiGet<BlockDetail>(`/api/blocks/${hash}`, undefined, signal),
    enabled,
  });
}

/** Whether a cached query is a mail's text view, which lists its paragraphs with the choices. */
function isMailText(query: { queryKey: readonly unknown[] }): boolean {
  const [scope, , view, format] = query.queryKey;
  return scope === "mail" && view === "body" && format === "text";
}

/** The team's choice about a paragraph (D225); it takes effect at the next run. The mail texts
 *  already read show it at once, the block's page and lists after asking again. */
export function useSaveBlockOverride() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ hash, ...update }: BlockOverrideUpdate & { hash: string }) =>
      apiPut<BlockInfo>(`/api/blocks/${hash}/override`, update),
    onSuccess: (block) => {
      queryClient.setQueryData<BlockDetail>(
        blockKeys.detail(block.hash),
        (detail) => detail && { ...detail, block },
      );
      void queryClient.invalidateQueries({ queryKey: blockKeys.all });
      queryClient.setQueriesData<MailText>({ predicate: isMailText }, (text) =>
        text?.paragraphs?.some((paragraph) => paragraph.hash === block.hash)
          ? {
              ...text,
              paragraphs: text.paragraphs.map((paragraph) =>
                paragraph.hash === block.hash
                  ? { ...paragraph, override: block.override }
                  : paragraph,
              ),
            }
          : text,
      );
    },
  });
}

// The page "Einstellungen" (D313 to D315) -------------------------------------------------------

export const settingsKeys = { all: ["settings"] as const };

export function useSettings() {
  return useQuery({
    queryKey: settingsKeys.all,
    queryFn: ({ signal }) => apiGet<SettingsView>("/api/settings", undefined, signal),
  });
}

/** A save takes the server's answer and loads everything else again: a setting may change any
 *  view (the AI page, the signals, the map, the standard blocks). */
export function useSaveSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: SettingsUpdate) => apiPut<SettingsView>("/api/settings", update),
    onSuccess: (view) => {
      queryClient.setQueryData(settingsKeys.all, view);
      void queryClient.invalidateQueries({
        predicate: (query) => query.queryKey[0] !== settingsKeys.all[0],
      });
    },
  });
}

// Hide rules (D221 to D223) ---------------------------------------------------------------------

export const hideKeys = {
  /** Under the research prefix: a note, an Akte, a bookmark or "relevant" changes which matches
   *  stay visible (D203), and every research write refreshes the research file. */
  rules: ["research", "hide-rules"] as const,
  suggestions: ["research", "hide-rules", "suggestions"] as const,
  /** Under the mail list's prefix: a change of the research file or of the rules changes it. */
  preview: (fields: HideRuleFields) => ["mails", "hide-rule-preview", fields] as const,
};

/** How long the criteria must stay unchanged before the preview asks (D223). */
export const HIDE_PREVIEW_DELAY = 300;

/** Every rule, newest first, with the mails the enabled ones hide and keep visible. */
export function useHideRules() {
  return useQuery({
    queryKey: hideKeys.rules,
    queryFn: ({ signal }) => apiGet<HideRuleList>("/api/hide-rules", undefined, signal),
  });
}

/** The mailing lists and automated senders with most mails that no enabled rule names. */
export function useHideSuggestions() {
  return useQuery({
    queryKey: hideKeys.suggestions,
    queryFn: ({ signal }) =>
      apiGet<HideSuggestion[]>("/api/hide-rules/suggestions", undefined, signal),
  });
}

/** What a rule with these criteria would hide, asked once they rest for HIDE_PREVIEW_DELAY.
 *  Each set of criteria is a query of its own, so the answer shown belongs to the criteria last
 *  asked for, whatever order the answers arrive in; until the next one arrives the last stays,
 *  marked stale. null asks nothing. */
export function useHideRulePreview(fields: HideRuleFields | null) {
  const settled = useDebounced(fields, HIDE_PREVIEW_DELAY);
  const asked = fields === null ? null : settled;
  const preview = useQuery({
    queryKey: hideKeys.preview(asked ?? {}),
    queryFn: () => apiPost<HideRulePreview>("/api/hide-rules/preview", asked),
    enabled: asked !== null,
    placeholderData: keepPreviousData,
  });
  const stale = preview.isPlaceholderData || hashKey([asked]) !== hashKey([fields]);
  return { preview, stale };
}

/** After a rule is saved or deleted: its list, the suggestions, the mail lists with their
 *  figures and previews, and the mail details (which name a mail's rules) are loaded again. */
function refreshHidden(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: hideKeys.rules });
  void queryClient.invalidateQueries({ queryKey: queryKeys.mails });
  void queryClient.invalidateQueries({ queryKey: ["mail"] });
}

function useHideRuleWrite<V, R>(write: (variables: V) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: write, onSuccess: () => refreshHidden(queryClient) });
}

export function useCreateHideRule() {
  return useHideRuleWrite((fields: HideRuleFields) =>
    apiPost<HideRuleInfo>("/api/hide-rules", fields),
  );
}

/** Every field anew, enabled included. */
export function useUpdateHideRule() {
  return useHideRuleWrite(({ id, ...update }: HideRuleUpdate & { id: number }) =>
    apiPut<HideRuleInfo>(`/api/hide-rules/${id}`, update),
  );
}

export function useDeleteHideRule() {
  return useHideRuleWrite((id: number) => apiDelete(`/api/hide-rules/${id}`));
}

// Places and maps (D240 to D249) ----------------------------------------------------------------

export const placeKeys = {
  summary: ["places", "summary"] as const,
  /** Under the mail list's prefix: a research write or a hide rule changes which mails match. */
  photos: (params: PlaceParams) => ["mails", "places", "photos", params] as const,
  texts: (params: PlaceParams) => ["mails", "places", "texts", params] as const,
  events: (params: PlaceParams) => ["mails", "places", "events", params] as const,
  photoList: (params: PhotoListParams) => ["mails", "places", "photo-list", params] as const,
  photo: (id: number) => ["places", "photo", id] as const,
  towns: ["map", "towns"] as const,
  mapStatus: ["map", "status"] as const,
};

/** Photos, devices and what the places step found; it changes with an import run. */
export function usePlaceSummary() {
  return useQuery({
    queryKey: placeKeys.summary,
    queryFn: ({ signal }) => apiGet<PlaceSummary>("/api/places/summary", undefined, signal),
  });
}

/** The three layers of the map (D247); the previous answer stays while the next loads, so a
 *  layer keeps its points while a filter changes. */
export function usePhotoPoints(params: PlaceParams, enabled = true) {
  return useQuery({
    queryKey: placeKeys.photos(params),
    queryFn: ({ signal }) => apiGet<PhotoPoints>("/api/places/photos", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useTextPlaces(params: PlaceParams, enabled = true) {
  return useQuery({
    queryKey: placeKeys.texts(params),
    queryFn: ({ signal }) => apiGet<TextPlaces>("/api/places/texts", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useEventPlaces(params: PlaceParams, enabled = true) {
  return useQuery({
    queryKey: placeKeys.events(params),
    queryFn: ({ signal }) => apiGet<EventPlaces>("/api/places/events", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** One photo with its mails and the nearest town (D248). */
export function usePhotoDetail(id: number, enabled = true) {
  return useQuery({
    queryKey: placeKeys.photo(id),
    queryFn: ({ signal }) => apiGet<PhotoDetail>(`/api/places/photos/${id}`, undefined, signal),
    enabled,
  });
}

/** "Fotos im Umkreis" (with a point) and "Fotos dieses Geräts" (a device, no point). */
export function usePhotoList(params: PhotoListParams, enabled = true) {
  return useQuery({
    queryKey: placeKeys.photoList(params),
    queryFn: ({ signal }) => apiGet<PhotoList>("/api/places/photo-list", params, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** The overview map's town labels (D244); they change only with a new release. */
export function useMapTowns() {
  return useQuery({
    queryKey: placeKeys.towns,
    queryFn: ({ signal }) => apiGet<TownLabel[]>("/api/map/towns", undefined, signal),
    staleTime: Infinity,
  });
}

/** How often the map status is asked for: every 2 s while a download runs (D246), else every
 *  30 s, which also notices a run started on a command line. */
export function mapStatusInterval(status: MapStatus | undefined): number {
  return status?.job?.alive ? 2_000 : 30_000;
}

/** poll false: asked once, for the small maps, which only need to know the detail map. */
export function useMapStatus(poll = true) {
  return useQuery({
    queryKey: placeKeys.mapStatus,
    queryFn: ({ signal }) => apiGet<MapStatus>("/api/map/status", undefined, signal),
    refetchInterval: poll ? (query) => mapStatusInterval(query.state.data) : false,
  });
}

/** Puts the run an action returned into the cached status at once, then asks again. */
function showMapRun(queryClient: QueryClient, job: MapJob) {
  queryClient.setQueryData<MapStatus>(
    placeKeys.mapStatus,
    (status) => status && { ...status, job },
  );
  void queryClient.invalidateQueries({ queryKey: placeKeys.mapStatus });
}

/** Starts a download of a detail map, or continues a stopped one of the same choice (D246). */
export function useStartMapDownload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: MapDownloadRequest) => apiPost<MapJob>("/api/map/download", request),
    onSuccess: (job) => showMapRun(queryClient, job),
  });
}

export function useStopMapDownload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<MapJob>("/api/map/download/stop", {}),
    onSuccess: (job) => showMapRun(queryClient, job),
  });
}

/** Deletes the detail map and a stopped download's part, which frees their space. */
export function useDeleteDetailMap() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiDelete("/api/map/detail"),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: placeKeys.mapStatus }),
  });
}

// AI services (milestone 15, D180 to D189) ------------------------------------------------------

export const aiKeys = {
  /** Prefix of everything about the AI page; a queue change, a discard or a run changes it. */
  all: ["ai"] as const,
  status: ["ai", "status"] as const,
  tasks: (params: AiTaskParams) => ["ai", "tasks", params] as const,
  results: (params: AiResultParams) => ["ai", "results", params] as const,
  sendLog: ["ai", "send-log"] as const,
  // Milestone 17 (D307, D309): under "ai", so a queue change or a discard asks them again.
  summary: (params: AiSummaryParams) => ["ai", "summary", params] as const,
  facets: (filters: MailFilters) => ["ai", "facets", filters] as const,
  tags: (params: AiTagParams) => ["ai", "tags", params] as const,
};

/** How often the AI page asks for the status (D48): every 2 s while a run is alive, else every
 *  30 s, which also notices a run started on a command line. */
export function aiStatusInterval(status: AiStatus | undefined): number {
  return status?.job?.alive ? 2_000 : 30_000;
}

export function useAiStatus() {
  return useQuery({
    queryKey: aiKeys.status,
    queryFn: ({ signal }) => apiGet<AiStatus>("/api/ai/status", undefined, signal),
    refetchInterval: (query) => aiStatusInterval(query.state.data),
  });
}

/** Asks a service and runs its real test (D180); may take as long as MAILROBBE_AI_TIMEOUT. */
export function useCheckAiService() {
  return useMutation({
    mutationFn: (capability: string) =>
      apiPost<ServiceCheck>(`/api/ai/services/${capability}/check`, {}),
  });
}

/** After a change of the queue or of the results: the AI page, and documents whose text or task
 *  it changes, the mail lists' hit lines with them. */
function aiChanged(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: aiKeys.all });
  void queryClient.invalidateQueries({ queryKey: queryKeys.documents });
  void queryClient.invalidateQueries({ queryKey: ["mail"] }); // the attachments' OCR state
}

export function useEnqueueAi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: AiQueueRequest) => apiPost<AiQueued>("/api/ai/tasks", request),
    onSuccess: () => aiChanged(queryClient),
  });
}

/** Tasks newest first, a page at a time; asked again every 4 s while a run is alive. */
export function useAiTasks(params: AiTaskParams, alive = false) {
  return useInfiniteQuery({
    queryKey: aiKeys.tasks(params),
    queryFn: ({ pageParam, signal }) =>
      apiGet<AiTaskPage>("/api/ai/tasks", { ...params, cursor: pageParam ?? undefined }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
    refetchInterval: alive ? 4_000 : false,
  });
}

export function useAiTaskAction(action: "retry" | "cancel") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AiTaskAction) => apiPost<AiChanged>(`/api/ai/tasks/${action}`, body),
    onSuccess: () => aiChanged(queryClient),
  });
}

export function useAiResults(params: AiResultParams, alive = false) {
  return useInfiniteQuery({
    queryKey: aiKeys.results(params),
    queryFn: ({ pageParam, signal }) =>
      apiGet<AiResultPage>(
        "/api/ai/results",
        { ...params, cursor: pageParam ?? undefined },
        signal,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    placeholderData: keepPreviousData,
    refetchInterval: alive ? 4_000 : false,
  });
}

/** Discards one result (its id) or every valid result of a run (job). */
export function useDiscardAi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target: { result: number } | { job: number }) =>
      apiPost<AiChanged>(
        "result" in target
          ? `/api/ai/results/${target.result}/discard`
          : `/api/ai/jobs/${target.job}/discard`,
        {},
      ),
    onSuccess: () => {
      aiChanged(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.mails });
    },
  });
}

export function useAiSendLog(enabled: boolean) {
  return useInfiniteQuery({
    queryKey: aiKeys.sendLog,
    queryFn: ({ pageParam, signal }) =>
      apiGet<AiSendLogPage>("/api/ai/send-log", { cursor: pageParam ?? undefined }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled,
  });
}

/** Puts the run an action returned into the cached status at once, then asks again. */
function showAiRun(queryClient: QueryClient, job: AiJob) {
  queryClient.setQueryData<AiStatus>(aiKeys.status, (status) => status && { ...status, job });
  void queryClient.invalidateQueries({ queryKey: aiKeys.all });
  void queryClient.invalidateQueries({ queryKey: queryKeys.importStatus });
}

export function useStartAiRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: AiRunRequest) => apiPost<AiJob>("/api/ai/run", request),
    onSuccess: (job) => showAiRun(queryClient, job),
  });
}

export function useStopAiRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<AiJob>("/api/ai/run/stop", {}),
    onSuccess: (job) => showAiRun(queryClient, job),
  });
}

// Summaries and AI tags (milestone 17, D300 to D311) ------------------------------------------

/** The card "KI-Zusammenfassung" of one mail or document (D307); asked again every 3 s while its
 *  task is open, so the summary shows without a reload. */
export function useAiSummary(params: AiSummaryParams, enabled = true) {
  return useQuery({
    queryKey: aiKeys.summary(params),
    queryFn: ({ signal }) => apiGet<AiSummaryView>("/api/ai/summary", params, signal),
    enabled,
    refetchInterval: (query) => (query.state.data?.task ? OCR_POLL : false),
  });
}

/** AI tags and themes among the mails of a filter (D309). */
export function useAiFacets(filters: MailFilters, enabled = true) {
  return useQuery({
    queryKey: aiKeys.facets(filters),
    queryFn: ({ signal }) => apiGet<AiFacets>("/api/ai/facets", filters, signal),
    enabled,
    placeholderData: keepPreviousData,
  });
}

/** AI tags by id (the chips of a filter) or by part of their name (D309). */
export function useAiTags(params: AiTagParams, enabled = true) {
  return useQuery({
    queryKey: aiKeys.tags(params),
    queryFn: ({ signal }) => apiGet<AiTagCount[]>("/api/ai/tags", params, signal),
    enabled,
  });
}

/** Adds the team tag of an AI tag's name to its mails (D310): the research data changes. */
export function useAdoptAiTag() {
  return useResearchWrite(({ tagId, ...body }: AiTagAdopt & { tagId: number }) =>
    apiPost<AiTagAdopted>(`/api/ai/tags/${tagId}/adopt`, body),
  );
}
