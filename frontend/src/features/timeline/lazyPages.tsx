import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The timeline comes in its own chunk on the first visit, so the screens most used (mail list
// and detail) do not load its chart; the compact histogram above the mail list is separate.
const Page = lazy(() =>
  import("./TimelinePage").then(({ TimelinePage }) => ({ default: TimelinePage })),
);

export function TimelineRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Zeitachse wird geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
