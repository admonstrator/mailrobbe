import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The hide rules come in their own chunk on the first visit; what the mail list, the mail
// detail and the search menu share with them stays in the main chunk.
const Page = lazy(() => import("./HidingPage").then(({ HidingPage }) => ({ default: HidingPage })));

export function HidingRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Ausblendregeln werden geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
