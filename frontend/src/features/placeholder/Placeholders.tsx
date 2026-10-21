// Screens of later milestones (SPEC 8) and the 404 page.

import type { ReactNode } from "react";
import { Link, useParams } from "react-router";

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

export function PersonsPlaceholder() {
  return (
    <Placeholder title="Personen">
      Die Personenübersicht mit Suche, Kennzahlen und Zusammenführung von Adressen folgt mit
      Meilenstein 5.
    </Placeholder>
  );
}

export function PersonPlaceholder() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) return <NotFoundPage />;
  return (
    <Placeholder
      title="Personenprofil"
      actions={
        <Link to={`/mails?person=${id}`} className={buttonClass("primary")}>
          Alle Mails dieser Person
        </Link>
      }
    >
      Das Profil mit Kennzahlen, wichtigsten Kontakten und Aktivität pro Jahr folgt mit Meilenstein
      5.
    </Placeholder>
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
