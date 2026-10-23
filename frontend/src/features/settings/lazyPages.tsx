import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The page "Einstellungen" comes in its own chunk (D313).
const Page = lazy(() =>
  import("./SettingsPage").then(({ SettingsPage }) => ({ default: SettingsPage })),
);

export function SettingsRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Einstellungen werden geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
