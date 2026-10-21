import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import { importStatusInterval, runAlive } from "../../api/queries";
import type { ImportJob, MboxFileInfo } from "../../api/types";
import {
  dkimJobDone,
  dkimJobRunning,
  importDefaults,
  importJob,
  importStatus,
  importStatusEmpty,
  importStatusPaused,
  scanResult,
} from "../../test/fixtures";
import { actionErrorText, scanSummary } from "./labels";
import {
  canResume,
  fileRows,
  importRunState,
  settingsValues,
  startRequest,
  stepState,
} from "./model";

const job = (patch: Partial<ImportJob>): ImportJob => ({ ...importJob, ...patch });
const paths = (rows: ReturnType<typeof fileRows>) =>
  rows.map((row) => (row.type === "file" ? row.file.path : row.type));

describe("run state", () => {
  it("follows status, liveness and a requested stop", () => {
    expect(importRunState(null)).toBe("none");
    expect(importRunState(importJob)).toBe("running");
    expect(importRunState(job({ stop_requested: true }))).toBe("pausing");
    expect(importRunState(job({ status: "stopped", alive: false }))).toBe("paused");
    expect(importRunState(job({ status: "done", alive: false }))).toBe("done");
    expect(importRunState(job({ status: "failed", alive: false }))).toBe("aborted");
    // Still running in the table, but nobody holds the lock: the process died (D47).
    expect(importRunState(job({ alive: false }))).toBe("orphaned");
  });

  it("shows steps as reported while the run lives, and how far a dead one got", () => {
    const states = (alive: boolean) =>
      importJob.progress.steps.slice(0, 3).map((step) => stepState(step, alive));
    expect(states(true)).toEqual(["done", "skipped", "running"]);
    expect(states(false)).toEqual(["done", "skipped", "aborted"]);
    expect(stepState(importJob.progress.steps[3], true)).toBe("waiting");
    expect(stepState(importJob.progress.steps[3], false)).toBe("unreached");
  });

  it("offers to resume what did not get to its end", () => {
    expect(canResume(importStatusPaused)).toBe(true);
    expect(canResume(importStatusEmpty)).toBe(false);
    const done = { ...importStatusEmpty, import_job: job({ status: "done", alive: false }) };
    expect(canResume(done)).toBe(false);
    expect(canResume({ ...done, import_job: job({ alive: false }) })).toBe(true);
    const halfDone: MboxFileInfo = { ...importStatus.files[60], bytes_done: 1024 };
    expect(canResume({ ...done, files: [halfDone] })).toBe(true);
  });

  it("polls every 2 s while an import or a DKIM run is alive, else every 15 s", () => {
    expect(importStatusInterval(undefined)).toBe(15_000);
    expect(importStatusInterval(importStatus)).toBe(2_000);
    expect(importStatusInterval(importStatusPaused)).toBe(15_000);
    const dkim = { ...importStatusPaused, dkim_job: dkimJobRunning };
    expect(runAlive(dkim)).toBe(true);
    expect(importStatusInterval(dkim)).toBe(2_000);
    const dead = { ...importStatus, import_job: job({ alive: false }), dkim_job: dkimJobDone };
    expect(importStatusInterval(dead)).toBe(15_000);
  });
});

describe("file rows", () => {
  const files = importStatus.files;

  it("group done, running, failed and waiting files and collapse the done and waiting ones", () => {
    const rows = fileRows(files, "all", new Set());
    expect(paths(rows).slice(0, 4)).toEqual([
      "export-2008-Q1.mbox",
      "export-2008-Q2.mbox",
      "more",
      "export-2020-Q1.mbox",
    ]);
    expect(rows[2]).toEqual({ type: "more", status: "done", hidden: 46 });
    expect(paths(rows).at(-2)).toBe("export-2022-Q2.mbox");
    expect(rows.at(-1)).toEqual({ type: "more", status: "pending", hidden: 14 });
    expect(rows).toHaveLength(2 + 1 + 8 + 1 + 1 + 1);
  });

  it("show every file of a group when expanded or filtered", () => {
    const done = fileRows(files, "all", new Set(["done"]));
    expect(done).toHaveLength(48 + 1 + 8 + 1 + 1 + 1);
    expect(done[48]).toEqual({ type: "less", status: "done" });
    const waiting = fileRows(files, "all", new Set(["pending"]));
    expect(waiting).toHaveLength(2 + 1 + 8 + 1 + 15 + 1);
    expect(paths(waiting).at(-2)).toBe("export-2025-Q4.mbox");
    expect(waiting.at(-1)).toEqual({ type: "less", status: "pending" });
    expect(fileRows(files, "done", new Set())).toHaveLength(48);
    expect(fileRows(files, "pending", new Set())).toHaveLength(15);
    expect(paths(fileRows(files, "error", new Set()))).toEqual(["export-2022-Q1.mbox"]);
  });

  it("do not collapse short groups", () => {
    const waiting = files.filter((file) => file.status === "pending");
    const few = [
      ...files.slice(44).filter((file) => file.status !== "pending"),
      ...waiting.slice(0, 3),
    ];
    expect(fileRows(few, "all", new Set()).filter((row) => row.type !== "file")).toEqual([]);
  });
});

describe("settings", () => {
  it("show the defaults until a field is edited", () => {
    expect(settingsValues(importDefaults, {})).toEqual({
      workers: "8",
      hashLimitMb: "50",
      nameservers: "1.1.1.1, 9.9.9.9",
    });
    expect(settingsValues(importDefaults, { workers: "" }).workers).toBe("");
  });

  it("send the fields that differ from the defaults", () => {
    expect(startRequest(importDefaults, {})).toEqual({ request: {} });
    expect(
      startRequest(importDefaults, {
        workers: "8",
        hashLimitMb: "50",
        nameservers: "1.1.1.1,9.9.9.9",
      }),
    ).toEqual({ request: {} });
    expect(
      startRequest(importDefaults, { workers: " 4 ", hashLimitMb: "20", nameservers: "9.9.9.9 " }),
    ).toEqual({
      request: { workers: 4, attachment_hash_limit: 20 * 1024 ** 2, dkim_nameservers: "9.9.9.9" },
    });
    expect(startRequest(importDefaults, { nameservers: "" })).toEqual({
      request: { dkim_nameservers: "" },
    });
  });

  it("name a field that cannot be used", () => {
    expect(startRequest(importDefaults, { workers: "0" })).toEqual({
      problem: "Parallele Worker: eine ganze Zahl von 1 bis 64.",
    });
    expect(startRequest(importDefaults, { workers: "65" })).toHaveProperty("problem");
    expect(startRequest(importDefaults, { hashLimitMb: "2,5" })).toEqual({
      problem: "Anhang-Limit für Hash: eine ganze Zahl in MB.",
    });
  });
});

describe("notices", () => {
  it("summarise a rescan, leaving out what did not happen", () => {
    expect(scanSummary(scanResult)).toBe(
      "74 Dateien gefunden, 2 neu, 1 geändert (werden neu importiert), 1 nicht lesbar; 19 zu importieren",
    );
    expect(
      scanSummary({ files: 1, pending: 0, new: [], replaced: [], missing: ["a"], unreadable: [] }),
    ).toBe("1 Datei gefunden, 1 fehlt; nichts zu importieren");
    expect(
      scanSummary({ files: 72, pending: 0, new: [], replaced: [], missing: [], unreadable: [] }),
    ).toBe("72 Dateien gefunden, keine Änderungen; nichts zu importieren");
  });

  it("explain a refused action by its code", () => {
    expect(actionErrorText(new ApiError(409, "job_running", "import running"))).toBe(
      "Es läuft bereits ein Import oder eine DKIM-Prüfung.",
    );
    expect(actionErrorText(new ApiError(400, "invalid_option", "workers: 99 > 64"))).toBe(
      "Eine Einstellung ist ungültig: workers: 99 > 64",
    );
    expect(actionErrorText(new ApiError(502, null, "HTTP 502"))).toMatch(/Server/);
  });
});
