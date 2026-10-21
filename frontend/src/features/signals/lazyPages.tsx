import { lazy, Suspense } from "react";

import { Spinner } from "../../components/Spinner";

// The signal overview comes in its own chunk on the first visit; the parts the mail list, the
// mail detail and the profile share with it (names, rules, links) stay in the main chunk.
const Page = lazy(() =>
  import("./SignalsPage").then(({ SignalsPage }) => ({ default: SignalsPage })),
);

export function SignalsRoute() {
  return (
    <Suspense
      fallback={
        <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
          <Spinner label="Signale werden geladen" />
        </div>
      }
    >
      <Page />
    </Suspense>
  );
}
