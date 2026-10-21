import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

import { listSearch, parseListState, type ListState } from "./listState";

/** The list state of the current URL and a setter that navigates to another one (a new history
 *  entry, so back and forward step through filter changes). */
export function useListState(): [ListState, (next: ListState) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseListState(searchParams), [searchParams]);
  const setState = useCallback(
    (next: ListState) => setSearchParams(listSearch(next), { preventScrollReset: true }),
    [setSearchParams],
  );
  return [state, setState];
}
