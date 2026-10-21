// Screens of later milestones (SPEC 8) and the 404 page.

import type { ReactNode } from "react";
import { Link } from "react-router";

import { buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import styles from "./Placeholders.module.css";

function Placeholder({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <main className={styles.page}>
      <title>{`${title} · Mailrobbe`}</title>
      <Card className={styles.card}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.text}>{children}</p>
        <div className={styles.actions}>
          {actions ?? (
            <Link to="/mails" className={buttonClass()}>
              Zur Mailliste
            </Link>
          )}
        </div>
      </Card>
    </main>
  );
}

export function GraphPlaceholder() {
  return (
    <Placeholder title="Beziehungskarte">
      Die Karte, wer mit wem wie oft schreibt, folgt mit Meilenstein 6.
    </Placeholder>
  );
}

export function ImportPlaceholder() {
  return (
    <Placeholder title="Import">
      Das Import-Dashboard mit Fortschritt je MBOX-Datei, Durchsatz und Fehlerprotokoll folgt mit
      Meilenstein 7.
    </Placeholder>
  );
}

export function NotFoundPage() {
  return (
    <Placeholder title="Seite nicht gefunden">
      Unter dieser Adresse gibt es in Mailrobbe nichts.
    </Placeholder>
  );
}
