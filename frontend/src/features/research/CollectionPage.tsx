import { lazy, Suspense } from "react";

import { ScreenLoading } from "./AktenPage";

const CollectionScreen = lazy(() =>
  import("./CollectionScreen").then(({ CollectionScreen }) => ({ default: CollectionScreen })),
);

/** /akten/:id: one Akte (D58); see CollectionScreen. */
export function CollectionPage() {
  return (
    <Suspense fallback={<ScreenLoading label="Akte wird geladen" />}>
      <CollectionScreen />
    </Suspense>
  );
}
