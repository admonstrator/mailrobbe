// The 404 page.

import type { ReactNode } from "react";
import { Link } from "react-router";

import { buttonClass } from "../../components/Button";
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
      <div className={styles.box}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.text}>{children}</p>
        <div className={styles.actions}>
          {actions ?? (
            <Link to="/mails" className={buttonClass()}>
              Zur Mailliste
            </Link>
          )}
        </div>
      </div>
    </main>
  );
}

export function NotFoundPage() {
  return (
    <Placeholder title="Seite nicht gefunden">
      Unter dieser Adresse gibt es in Mailrobbe nichts.
    </Placeholder>
  );
}
