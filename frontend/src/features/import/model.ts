// The import dashboard's logic outside React: the state of the latest run, the rows of the file
// table and the start request from the settings form (D46 to D49).

import type {
  ImportJob,
  ImportOptions,
  ImportStartRequest,
  ImportStatus,
  MboxFileInfo,
  MboxStatus,
  StepProgress,
  StepStatus,
} from "../../api/types";

/** What the run card says about the latest import run. */
export type RunState = "none" | "running" | "pausing" | "paused" | "done" | "aborted" | "orphaned";

export function importRunState(job: ImportJob | null): RunState {
  if (!job) return "none";
  if (job.status === "running") {
    // Running without its lock: the process ended without recording it, say because the server
    // was restarted (D47, D110).
    if (!job.alive) return "orphaned";
    return job.stop_requested ? "pausing" : "running";
  }
  if (job.status === "stopped") return "paused";
  return job.status === "done" ? "done" : "aborted";
}

/** A step as the dashboard shows it (D110): as reported while its run lives; afterwards a step
 *  that never started was not reached, and one a dead process left running was cut off. */
export type StepState = StepStatus | "unreached" | "aborted";

export function stepState(step: StepProgress, alive: boolean): StepState {
  if (alive) return step.status;
  if (step.status === "waiting") return "unreached";
  return step.status === "running" ? "aborted" : step.status;
}

/** Seconds without a report after which a live run is said to be silent; it reports every 2 s. */
export const SILENT_SECONDS = 30;

/** "Import fortsetzen" instead of "Import starten": the last run did not get to its end, or files
 *  wait half done (paused, or interrupted before runs were recorded). */
export function canResume(status: ImportStatus): boolean {
  const job = status.import_job;
  if (job && job.status !== "done") return true;
  return status.files.some(
    (file) => file.status === "paused" || (file.status === "pending" && file.bytes_done > 0),
  );
}

/** The status filter of the file table. */
export type FileFilter = "all" | MboxStatus;

/** Groups of the file table, top to bottom: what is done, then what runs, stopped or waits. */
export const FILE_GROUPS: readonly MboxStatus[] = ["done", "running", "paused", "error", "pending"];

/** Done and waiting files beyond the first few collapse into one row per group, as in the
 *  mockup: at the start of an import nearly every file waits, at its end nearly every one is done. */
export const SHOWN_COLLAPSED: Partial<Record<MboxStatus, number>> = { done: 2, pending: 1 };

export type FileRow =
  | { type: "file"; file: MboxFileInfo }
  | { type: "more"; status: MboxStatus; hidden: number }
  | { type: "less"; status: MboxStatus };

/** The table's rows: files by group, by path inside each (the API's order, so rows keep their
 *  place while polling). Without a filter, long groups collapse into an expandable row. */
export function fileRows(
  files: MboxFileInfo[],
  filter: FileFilter,
  expanded: ReadonlySet<MboxStatus>,
): FileRow[] {
  const rows: FileRow[] = [];
  for (const status of FILE_GROUPS) {
    if (filter !== "all" && filter !== status) continue;
    const group = files.filter((file) => file.status === status);
    const keep = SHOWN_COLLAPSED[status];
    const collapsible = keep !== undefined && filter === "all" && group.length > keep + 2;
    const open = expanded.has(status);
    const shown = collapsible && !open ? group.slice(0, keep) : group;
    rows.push(...shown.map((file) => ({ type: "file" as const, file })));
    if (collapsible) {
      rows.push(
        open ? { type: "less", status } : { type: "more", status, hidden: group.length - keep },
      );
    }
  }
  return rows;
}

const MIB = 1024 ** 2;

/** The settings form as typed; a field left untouched is missing and shows the default. */
export interface SettingsDraft {
  workers?: string;
  hashLimitMb?: string;
  nameservers?: string;
}

/** The text of each field: the draft's, else the default's. */
export function settingsValues(defaults: ImportOptions, draft: SettingsDraft) {
  return {
    workers: draft.workers ?? String(defaults.workers),
    hashLimitMb: draft.hashLimitMb ?? String(Math.round(defaults.attachment_hash_limit / MIB)),
    nameservers: draft.nameservers ?? defaults.dkim_nameservers,
  };
}

const wholeNumber = (text: string) => (/^\d+$/.test(text.trim()) ? Number(text.trim()) : null);
const nameserverList = (text: string) =>
  text
    .split(/[\s,]+/)
    .filter(Boolean)
    .join(", ");

/** The start request with the fields that differ from the defaults (the server fills in the
 *  rest, D49), or the German reason why a field cannot be used. */
export function startRequest(
  defaults: ImportOptions,
  draft: SettingsDraft,
): { request: ImportStartRequest } | { problem: string } {
  const request: ImportStartRequest = {};
  if (draft.workers !== undefined) {
    const workers = wholeNumber(draft.workers);
    if (workers === null || workers < 1 || workers > 64) {
      return { problem: "Parallele Worker: eine ganze Zahl von 1 bis 64." };
    }
    if (workers !== defaults.workers) request.workers = workers;
  }
  if (draft.hashLimitMb !== undefined) {
    const megabytes = wholeNumber(draft.hashLimitMb);
    if (megabytes === null) return { problem: "Anhang-Limit für Hash: eine ganze Zahl in MB." };
    const shown = Math.round(defaults.attachment_hash_limit / MIB);
    if (megabytes !== shown) request.attachment_hash_limit = megabytes * MIB;
  }
  if (draft.nameservers !== undefined) {
    const nameservers = nameserverList(draft.nameservers);
    if (nameservers !== nameserverList(defaults.dkim_nameservers)) {
      request.dkim_nameservers = nameservers;
    }
  }
  return { request };
}
