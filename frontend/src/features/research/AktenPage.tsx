import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The research screens come in a chunk of their own on the first visit, as the map does.
const AktenScreen = lazy(() =>
  import("./AktenScreen").then(({ AktenScreen }) => ({ default: AktenScreen })),
);

/** /akten: the research file at a glance (D57 to D64); see AktenScreen. */
export function AktenPage() {
  return (
    <Suspense fallback={<ScreenLoading label="Akten werden geladen" />}>
      <AktenScreen />
    </Suspense>
  );
}

export function ScreenLoading({ label }: { label: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
      <Spinner label={label} />
    </div>
  );
}
