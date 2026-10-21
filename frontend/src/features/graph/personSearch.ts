// The person search of the Zentrum field: the person list (GET /api/persons, D31) for q.

import { usePersonPage } from "../../api/queries";

export const PERSON_SEARCH_LIMIT = 8;

/** Persons whose address or name contains q, most mails first; nothing for an empty q. */
export function usePersonSearch(q: string) {
  return usePersonPage({ q, limit: PERSON_SEARCH_LIMIT }, q !== "");
}
