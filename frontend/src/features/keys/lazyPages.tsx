import { lazy, Suspense, type ReactNode } from "react";

import { Spinner } from "../../components/Spinner";

// The selector screens come in their own chunk on the first visit; the dashboard's card and the
// mail detail's DKIM box share only the labels and the origin badge with them.
const ListPage = lazy(() =>
  import("./SelectorListPage").then(({ SelectorListPage }) => ({ default: SelectorListPage })),
);
const DetailPage = lazy(() =>
  import("./SelectorDetailPage").then(({ SelectorDetailPage }) => ({
    default: SelectorDetailPage,
  })),
);

function Loading({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Selektoren werden geladen" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function SelectorListRoute() {
  return (
    <Loading>
      <ListPage />
    </Loading>
  );
}

export function SelectorDetailRoute() {
  return (
    <Loading>
      <DetailPage />
    </Loading>
  );
}
