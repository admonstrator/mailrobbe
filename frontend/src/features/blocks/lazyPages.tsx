import { lazy, Suspense, type ReactNode } from "react";

import { Spinner } from "../../components/Spinner";

// The standard block screens come in their own chunk on the first visit; the parts the mail
// detail shares with them stay in the main chunk.
const List = lazy(() => import("./BlocksPage").then(({ BlocksPage }) => ({ default: BlocksPage })));
const Detail = lazy(() =>
  import("./BlockDetailPage").then(({ BlockDetailPage }) => ({ default: BlockDetailPage })),
);

function Loading({ children }: { children: ReactNode }) {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Standardblöcke werden geladen" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}

export function BlocksRoute() {
  return (
    <Loading>
      <List />
    </Loading>
  );
}

export function BlockDetailRoute() {
  return (
    <Loading>
      <Detail />
    </Loading>
  );
}
