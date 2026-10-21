// The person search of the Zentrum field: GET /api/persons?q=&limit= from milestone 5. Its answer
// is typed here in the agreed shape until it is part of api/types.ts.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiGet } from "../../api/client";

export interface PersonSearchItem {
  id: number; // a root person
  name: string | null;
  email: string;
  domain: string;
  aliases: number;
  figures: {
    mails: number;
    sent: number;
    received: number;
    cc_only: number;
    contacts: number;
    first_date: string | null;
    last_date: string | null;
    dkim_pass_ratio: number | null;
  };
}

export interface PersonSearchPage {
  items: PersonSearchItem[];
  next_cursor: string | null;
  prev_cursor: string | null;
  total: number;
}

export const PERSON_SEARCH_LIMIT = 8;

/** Persons whose address or name contains q; nothing for an empty q. */
export function usePersonSearch(q: string) {
  return useQuery({
    queryKey: ["persons", "search", q],
    queryFn: ({ signal }) =>
      apiGet<PersonSearchPage>("/api/persons", { q, limit: PERSON_SEARCH_LIMIT }, signal),
    enabled: q !== "",
    placeholderData: keepPreviousData,
  });
}
