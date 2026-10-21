import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The map screen comes in its own chunk on the first visit (Cytoscape in another one), so the
// rest of the app does not load it.
const GraphScreen = lazy(() =>
  import("./GraphScreen").then(({ GraphScreen }) => ({ default: GraphScreen })),
);

export function GraphPage() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Karte wird geladen" />
        </div>
      }
    >
      <GraphScreen />
    </Suspense>
  );
}
