// Thin fetch wrapper for the backend's /api: query strings from parameter objects, JSON bodies,
// and contract errors as ApiError.

import type { ApiErrorDetail, ErrorCode } from "./types";

type ParamValue = string | number | boolean | null | undefined | readonly (string | number)[];
/** A parameter object such as MailListParams. */
type Params<P> = { [K in keyof P]?: ParamValue };

/** Query string of a parameter object: lists repeat their key, true is "true", and empty
 *  strings, false, null and undefined (the defaults) are left out. */
export function buildQuery<P extends Params<P>>(params: P): URLSearchParams {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params) as [string, ParamValue][]) {
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else if (value === true) {
      search.append(key, "true");
    } else if (typeof value === "number" || (typeof value === "string" && value !== "")) {
      search.append(key, String(value));
    }
  }
  return search;
}

/** path plus the query string of params, without "?" when there are none. */
export function withQuery<P extends Params<P>>(path: string, params?: P): string {
  const query = params ? buildQuery(params).toString() : "";
  return query ? `${path}?${query}` : path;
}

/** A failed request. code is the contract's ErrorCode when the backend sent one, else null
 *  (validation errors, server errors, proxies). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | null;

  constructor(status: number, code: ErrorCode | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function isErrorDetail(value: unknown): value is ApiErrorDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiErrorDetail).code === "string" &&
    typeof (value as ApiErrorDetail).message === "string"
  );
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    // not JSON
  }
  if (isErrorDetail(detail)) return new ApiError(response.status, detail.code, detail.message);
  return new ApiError(response.status, null, `HTTP ${response.status}`);
}

async function request<T>(method: string, url: string, body?: unknown, signal?: AbortSignal) {
  const response = await fetch(url, {
    method,
    signal,
    headers:
      body === undefined
        ? { Accept: "application/json" }
        : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await toApiError(response);
  return (await response.json()) as T;
}

export function apiGet<T, P extends Params<P> = Record<never, never>>(
  path: string,
  params?: P,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>("GET", withQuery(path, params), undefined, signal);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return request<T>("POST", path, body);
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PUT", path, body);
}
