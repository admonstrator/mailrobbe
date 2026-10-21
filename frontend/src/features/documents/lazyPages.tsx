import { lazy, Suspense, type ReactNode } from "react";

import { Spinner } from "../../components/Spinner";

// The document screens come in their own chunks on the first visit, so the screens most used
// (mail list and detail) do not load them; the parts those share (kind icons, labels) stay.
const ListPage = lazy(() =>
  import("./DocumentListPage").then(({ DocumentListPage }) => ({ default: DocumentListPage })),
);
const DetailPage = lazy(() =>
  import("./DocumentDetailPage").then(({ DocumentDetailPage }) => ({
    default: DocumentDetailPage,
  })),
);

function Loading({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Anhänge werden geladen" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function DocumentListRoute() {
  return (
    <Loading>
      <ListPage />
    </Loading>
  );
}

export function DocumentDetailRoute() {
  return (
    <Loading>
      <DetailPage />
    </Loading>
  );
}
