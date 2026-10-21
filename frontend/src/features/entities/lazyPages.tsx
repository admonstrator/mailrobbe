import { lazy, Suspense, type ReactNode } from "react";

import { Spinner } from "../../components/Spinner";

// The entity screens come in their own chunks on the first visit, so the mail list and the mail
// detail do not load them; the parts those share (labels, icons, links) stay in the main chunk.
const ListPage = lazy(() =>
  import("./EntityListPage").then(({ EntityListPage }) => ({ default: EntityListPage })),
);
const DetailPage = lazy(() =>
  import("./EntityDetailPage").then(({ EntityDetailPage }) => ({ default: EntityDetailPage })),
);

function Loading({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Entitäten werden geladen" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function EntityListRoute() {
  return (
    <Loading>
      <ListPage />
    </Loading>
  );
}

export function EntityDetailRoute() {
  return (
    <Loading>
      <DetailPage />
    </Loading>
  );
}
