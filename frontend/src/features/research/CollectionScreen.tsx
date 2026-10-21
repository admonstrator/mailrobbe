import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  useCollection,
  useDeleteCollection,
  useMailPage,
  useUpdateCollection,
} from "../../api/queries";
import {
  DESCRIPTION_LIMIT,
  NAME_LIMIT,
  type CollectionDetail,
  type MailListItem,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDate, formatDateTime, formatNumber } from "../../lib/format";
import styles from "./CollectionScreen.module.css";
import { ConfirmDialog } from "./ConfirmDialog";
import { ExportDialog } from "./ExportDialog";
import { InlineEdit } from "./InlineEdit";
import { collectionMailsHref, searchHref } from "./labels";

/** /akten/:id: one Akte (D58) with its figures, persons, searches and mails. */
export function CollectionScreen() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <main className={styles.page}>
        <CollectionNotFound />
      </main>
    );
  }
  return <CollectionView key={id} id={Number(id)} />;
}

function CollectionView({ id }: { id: number }) {
  const collection = useCollection(id);
  return (
    <main className={styles.page}>
      <title>{`${collection.data?.name ?? "Akte"} · Mailrobbe`}</title>
      <Link to="/akten" className={styles.back}>
        ‹ Alle Akten
      </Link>
      {collection.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Akte wird geladen" />
        </Card>
      ) : collection.isError ? (
        collection.error instanceof ApiError && collection.error.code === "not_found" ? (
          <CollectionNotFound id={id} />
        ) : (
          <Card>
            <ErrorState
              title="Die Akte konnte nicht geladen werden."
              actions={<Button onClick={() => void collection.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </Card>
        )
      ) : (
        <Collection collection={collection.data} />
      )}
    </main>
  );
}

function Collection({ collection }: { collection: CollectionDetail }) {
  const update = useUpdateCollection();
  const remove = useDeleteCollection();
  const navigate = useNavigate();
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const { id } = collection;

  return (
    <>
      <div className={styles.head}>
        <div className={styles.heading}>
          <InlineEdit
            value={collection.name}
            label="Name"
            maxLength={NAME_LIMIT}
            required
            onSave={(name) => update.mutateAsync({ id, name })}
          >
            <h1 className={styles.title}>{collection.name}</h1>
          </InlineEdit>
          <InlineEdit
            value={collection.description}
            label="Beschreibung"
            multiline
            maxLength={DESCRIPTION_LIMIT}
            onSave={(description) => update.mutateAsync({ id, description })}
          >
            <p className={cx(styles.description, !collection.description && styles.muted)}>
              {collection.description || "Noch keine Beschreibung."}
            </p>
          </InlineEdit>
          <p className={styles.meta}>
            Geändert {formatDateTime(collection.updated_at)}
            {collection.created_by && ` · angelegt von ${collection.created_by}`}
          </p>
        </div>
        <div className={styles.actions}>
          <Link to={collectionMailsHref(id)} className={buttonClass()}>
            In Mailliste öffnen
          </Link>
          <Button variant="primary" onClick={() => setExporting(true)}>
            Exportieren
          </Button>
          <Button
            onClick={() => {
              remove.reset();
              setDeleting(true);
            }}
          >
            Akte löschen
          </Button>
        </div>
      </div>

      <ul className={styles.tiles}>
        <Tile label="Mails" value={formatNumber(collection.mails)} />
        <Tile
          label="Zeitraum"
          value={
            collection.date_min && collection.date_max
              ? `${formatDate(collection.date_min)} – ${formatDate(collection.date_max)}`
              : "–"
          }
        />
        <Tile
          label="Nicht im Archiv"
          value={formatNumber(collection.missing)}
          title="Mails der Akte, deren Inhalt keine Mail des Archivs (mehr) hat, etwa nach einem neuen Import"
        />
      </ul>

      <div className={styles.columns}>
        <CollectionMails id={id} />
        <div className={styles.side}>
          <Card variant="side">
            <CardTitle variant="caps">Beteiligte Personen</CardTitle>
            {collection.persons.length === 0 ? (
              <p className={styles.muted}>Noch keine.</p>
            ) : (
              <ul className={styles.persons}>
                {collection.persons.map(({ person, mails }) => (
                  <li key={person.person_id}>
                    <PersonLink person={person} className={styles.person} />
                    <span className={styles.personCount}>{formatNumber(mails)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card variant="side">
            <CardTitle variant="caps">Gespeicherte Suchen</CardTitle>
            {collection.searches.length === 0 ? (
              <p className={styles.muted}>
                Noch keine. In der Mailliste lässt sich eine Suche speichern und dieser Akte
                zuordnen.
              </p>
            ) : (
              <ul className={styles.searches}>
                {collection.searches.map((search) => (
                  <li key={search.id}>
                    <Link to={searchHref(search.query)}>{search.name}</Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      {exporting && (
        <ExportDialog
          selection={{ filters: { collection: [id] } }}
          count={collection.mails}
          label={collection.name}
          onClose={() => setExporting(false)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Akte löschen"
          confirmLabel="Akte löschen"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setDeleting(false)}
          onConfirm={() => remove.mutate(id, { onSuccess: () => void navigate("/akten") })}
        >
          Die Akte „{collection.name}“ wird gelöscht. Ihre Mails, Notizen und Schlagworte bleiben;
          nur die Zuordnung zur Akte geht verloren, ihre gespeicherten Suchen gehören danach zu
          keiner Akte.
        </ConfirmDialog>
      )}
    </>
  );
}

function Tile({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <li className={styles.tile} title={title}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileValue}>{value}</span>
    </li>
  );
}

/** The newest mails of the Akte; each opens with the Akte as the list, so Vorherige and Nächste
 *  stay inside it. */
function CollectionMails({ id }: { id: number }) {
  const page = useMailPage({ collection: [id] });
  const listQuery = `collection=${id}`;
  return (
    <Card className={styles.mails} aria-labelledby="collection-mails">
      <div className={styles.mailsHead}>
        <CardTitle id="collection-mails">Mails</CardTitle>
        <span className={styles.muted}>neueste zuerst</span>
      </div>
      {page.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Mails werden geladen" />
        </div>
      ) : page.isError ? (
        <ErrorState
          title="Die Mails konnten nicht geladen werden."
          actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
        />
      ) : page.data.items.length === 0 ? (
        <EmptyState title="Noch keine Mail in dieser Akte">
          Mails kommen in der Mailliste oder in der Detailansicht einer Mail in die Akte.
        </EmptyState>
      ) : (
        <>
          <ul className={styles.mailList}>
            {page.data.items.map((mail) => (
              <MailRow key={mail.id} mail={mail} href={`/mails/${mail.id}?${listQuery}`} />
            ))}
          </ul>
          {page.data.next_cursor && (
            <Link to={collectionMailsHref(id)} className={styles.moreLink}>
              Weitere in der Mailliste ›
            </Link>
          )}
        </>
      )}
    </Card>
  );
}

function MailRow({ mail, href }: { mail: MailListItem; href: string }) {
  return (
    <li className={styles.mailRow}>
      <span className={styles.mailDate}>{mail.date ? formatDate(mail.date) : "–"}</span>
      <span className={styles.mailSender}>
        {mail.sender ? <PersonLink person={mail.sender} /> : "(unbekannt)"}
      </span>
      <Link to={href} className={cx(styles.mailSubject, !mail.subject && styles.muted)}>
        {mail.subject || "(ohne Betreff)"}
      </Link>
    </li>
  );
}

function CollectionNotFound({ id }: { id?: number }) {
  return (
    <Card>
      <ErrorState
        title="Diese Akte gibt es nicht."
        actions={
          <Link to="/akten" className={buttonClass()}>
            Zu den Akten
          </Link>
        }
      >
        {id === undefined
          ? "Die Adresse nennt keine gültige Akten-Nummer."
          : `Es gibt keine Akte mit der Nummer ${id}; vielleicht wurde sie gelöscht.`}
      </ErrorState>
    </Card>
  );
}
