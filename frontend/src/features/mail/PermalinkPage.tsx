import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { usePermalink } from "../../api/queries";
import { PERMALINK_DIGITS } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import styles from "./PermalinkPage.module.css";

/** /m/:hash opens the mail with this content (D61); the mail's URL replaces the permalink in
 *  the history, so Back leads to where the link was clicked. */
export function PermalinkPage() {
  const { hash = "" } = useParams();
  const navigate = useNavigate();
  const target = usePermalink(hash.toLowerCase());
  const mailId = target.data?.mail_id;

  useEffect(() => {
    if (mailId !== undefined) void navigate(`/mails/${mailId}`, { replace: true });
  }, [mailId, navigate]);

  return (
    <div className={styles.page}>
      <title>Permalink · Mailrobbe</title>
      {target.isError ? (
        <Card className={styles.message}>
          <PermalinkError error={target.error} hash={hash} onRetry={() => void target.refetch()} />
        </Card>
      ) : (
        <div className={styles.loading}>
          <Spinner label="Mail wird gesucht" />
        </div>
      )}
    </div>
  );
}

function PermalinkError({
  error,
  hash,
  onRetry,
}: {
  error: Error;
  hash: string;
  onRetry: () => void;
}) {
  const toList = (
    <Link to="/mails" className={buttonClass()}>
      Zur Mailliste
    </Link>
  );
  const code = error instanceof ApiError ? error.code : null;
  if (code === "not_found") {
    return (
      <ErrorState title="Keine Mail mit diesem Inhalt im Archiv." actions={toList}>
        Zum Permalink {hash} gibt es hier keine Mail. Vielleicht stammt er aus einem anderen Archiv,
        oder die Mail ist noch nicht importiert.
      </ErrorState>
    );
  }
  if (code === "ambiguous_permalink") {
    return (
      <ErrorState title="Der Link ist zu kurz." actions={toList}>
        Er nennt nur {formatNumber(hash.length)} Ziffern ({hash}), und die passen zu mehreren Mails
        mit verschiedenem Inhalt. Ein vollständiger Permalink hat {PERMALINK_DIGITS} Ziffern.
      </ErrorState>
    );
  }
  if (error instanceof ApiError && error.status < 500) {
    return (
      <ErrorState title="Das ist kein gültiger Permalink." actions={toList}>
        Ein Permalink besteht aus /m/ und {PERMALINK_DIGITS} Ziffern und Buchstaben von a bis f.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Der Permalink konnte nicht geöffnet werden."
      actions={
        <>
          <Button onClick={onRetry}>Erneut versuchen</Button>
          {toList}
        </>
      }
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}
