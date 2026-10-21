import { useState } from "react";

import { useUndoMerge } from "../../api/queries";
import type { MergeLogEntry } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { formatDateTime } from "../../lib/format";
import { personErrorText } from "./labels";
import styles from "./ProfileMerges.module.css";

/** The logged merges that brought aliases into this person (D163), each with "Zusammenführung
 *  rückgängig"; an address can still be split off alone in the head (D28). Shown while there
 *  are any, and after an undo for its confirmation. */
export function ProfileMerges({ merges }: { merges: MergeLogEntry[] }) {
  const undo = useUndoMerge();
  const [done, setDone] = useState<string | null>(null);

  if (merges.length === 0 && !done) return null;
  return (
    <Card className={styles.card}>
      <CardTitle>Zusammengeführt</CardTitle>
      <p role="status" className={done ? styles.notice : "sr-only"}>
        {done}
      </p>
      {undo.isError && (
        <p className={styles.error} role="alert">
          {personErrorText(undo.error)}
        </p>
      )}
      {merges.length > 0 && (
        <ul className={styles.list} aria-label="Zusammenführungen">
          {merges.map((merge) => {
            const emails = merge.moved.map((person) => person.email).join(", ");
            const verb = merge.moved.length === 1 ? "ist" : "sind";
            const onSuccess = () =>
              setDone(`Zusammenführung rückgängig gemacht: ${emails} ${verb} wieder eigenständig.`);
            return (
              <li key={merge.id} className={styles.row}>
                <div className={styles.what}>
                  <p className={styles.moved}>{emails}</p>
                  <p className={styles.meta}>
                    {formatDateTime(merge.created_at)}
                    {merge.editor && ` · ${merge.editor}`}
                    {merge.batch_id !== null && " · mit „Alle sicheren zusammenführen“"}
                  </p>
                </div>
                <Button
                  size="sm"
                  disabled={undo.isPending}
                  onClick={() => undo.mutate(merge.id, { onSuccess })}
                >
                  Zusammenführung rückgängig
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
