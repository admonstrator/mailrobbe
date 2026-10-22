import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The page "Orte" comes in its own chunk with MapLibre (D244), which only it and the small maps
// load.
const Page = lazy(() => import("./PlacesPage").then(({ PlacesPage }) => ({ default: PlacesPage })));

export function PlacesRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Orte werden geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
