import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The page "KI" comes in its own chunk (D187); the dashboard's run line and the document page's
// text card stay in theirs.
const Page = lazy(() => import("./AiPage").then(({ AiPage }) => ({ default: AiPage })));

export function AiRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="KI wird geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
