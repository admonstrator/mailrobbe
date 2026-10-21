import { useCallback, useMemo } from "react";
import { useLocation, useNavigate } from "react-router";

import { graphSearch, parseGraphState, type GraphState } from "./graphState";

/** The map state of the current URL and a setter that navigates to another one: a new history
 *  entry for a new excerpt, replace for the view options. */
export function useGraphState(): [GraphState, (next: GraphState, replace?: boolean) => void] {
  const { search } = useLocation();
  const navigate = useNavigate();
  const state = useMemo(() => parseGraphState(new URLSearchParams(search)), [search]);
  const setState = useCallback(
    (next: GraphState, replace = false) => {
      const query = graphSearch(next);
      void navigate({ pathname: "/karte", search: query ? `?${query}` : "" }, { replace });
    },
    [navigate],
  );
  return [state, setState];
}
