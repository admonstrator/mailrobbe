import { useCertainMergePlan } from "../../api/queries";
import type { CertainMergePlan } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import styles from "./BulkMergeDialog.module.css";
import { Dialog } from "./Dialog";
import { mergeCount, personCount, personErrorText } from "./labels";

/** The confirmation of "Alle sicheren zusammenführen" (D162), or with ai of "Alle sicheren
 *  KI-Treffer zusammenführen" (D326): what the run merges now, asked from the backend when the
 *  dialog opens. The parent runs it, so closing the dialog during the run only hides it. */
export function BulkMergeDialog({
  ai = false,
  running,
  error,
  onConfirm,
  onClose,
}: {
  ai?: boolean;
  running: boolean;
  error: Error | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const plan = useCertainMergePlan(true, ai);
  // The plan, when there is something to merge.
  const ready = plan.data && plan.data.merges > 0 ? plan.data : null;

  return (
    <Dialog
      title={
        ai ? "Alle sicheren KI-Treffer zusammenführen" : "Alle sicheren Vorschläge zusammenführen"
      }
      onClose={onClose}
    >
      <div className={styles.body}>
        {plan.isPending ? (
          <Spinner label="Wird berechnet" />
        ) : plan.isError ? (
          <p className={styles.error} role="alert">
            Was zusammengeführt würde, ließ sich nicht berechnen: {personErrorText(plan.error)}
          </p>
        ) : (
          <PlanText plan={plan.data} ai={ai} />
        )}
        {error && (
          <p className={styles.error} role="alert">
            {personErrorText(error)}
          </p>
        )}
      </div>
      <div className={styles.foot}>
        {running && (
          <span className={styles.running}>
            <Spinner label="Wird zusammengeführt" />
            Wird zusammengeführt …
          </span>
        )}
        <Button onClick={onClose} disabled={running}>
          {ready ? "Abbrechen" : "Schließen"}
        </Button>
        {ready && (
          <Button variant="primary" disabled={running} onClick={onConfirm}>
            {personCount(ready.persons)} zusammenführen
          </Button>
        )}
      </div>
    </Dialog>
  );
}

function PlanText({ plan, ai }: { plan: CertainMergePlan; ai: boolean }) {
  const leftOut = plan.left_out_groups > 0 && (
    <p>
      {plan.left_out_groups === 1 ? "Eine Gruppe" : `${plan.left_out_groups} Gruppen`} mit{" "}
      {personCount(plan.left_out_persons)} {plan.left_out_groups === 1 ? "bleibt" : "bleiben"}{" "}
      stehen:{" "}
      {ai
        ? "mehr als sechs Personen, ein verworfener Vorschlag oder ein Paar, das die KI für verschieden oder unklar hält."
        : "mehr als fünf Personen oder ein verworfener Vorschlag darin."}{" "}
      Diese bitte einzeln prüfen.
    </p>
  );
  if (plan.merges === 0) {
    return (
      <>
        <p>Gerade gibt es nichts, was sich auf einmal zusammenführen ließe.</p>
        {leftOut}
      </>
    );
  }
  return (
    <>
      <p>
        <strong>
          {personCount(plan.persons)} in {mergeCount(plan.merges)}
        </strong>
        :{" "}
        {ai
          ? "Die Personen, die die KI sicher für dieselbe hält, werden jeweils mit der Person zusammengeführt, die die meisten Mails hat, und sind dann ihre Aliase. Die KI kann sich auch dann irren."
          : "Die Personen, die sichere Vorschläge verbinden, werden jeweils mit der Person zusammengeführt, die die meisten Mails hat, und sind dann ihre Aliase."}
      </p>
      {leftOut}
      <p>
        Danach lassen sich die Zusammenführungen einzeln rückgängig machen und der ganze Lauf auf
        einmal, unter „Zuletzt zusammengeführt“. Kennzahlen, Karte und Vorschläge werden neu
        berechnet; das kann einen Moment dauern.
      </p>
    </>
  );
}
