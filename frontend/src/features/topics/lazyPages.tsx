import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The topics screen comes in its own chunk on the first visit, so the screens most used (mail
// list and detail) do not load it.
const Page = lazy(() => import("./TopicsPage").then(({ TopicsPage }) => ({ default: TopicsPage })));

export function TopicsRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Themen werden geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
