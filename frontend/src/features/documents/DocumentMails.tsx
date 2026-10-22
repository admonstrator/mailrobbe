import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useMailPage } from "../../api/queries";
import type { DocumentDetail } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { PageTooFar, Pagination } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { edgePages, FIRST_PAGE, listPagination } from "../../lib/paging";
import type { ColumnChoice } from "../mails/columns";
import { listSearch, toListParams } from "../mails/listState";
import { MailTable } from "../mails/MailTable";
import styles from "./DocumentMails.module.css";
import { documentMailList, documentMailsHref, type DocumentMailState } from "./urlState";

/** Date, sender, recipients and subject: who sent it when to whom. */
const COLUMNS: ColumnChoice = { to: true, attachment: false, size: false, mbox: false };
const noPath = () => "";

/** "Wer hat dieses Dokument wann an wen geschickt" (D75): the mail list's table over the mails
 *  carrying the document, oldest first, a page at a time. Opening a mail keeps this list, so
 *  Vorherige and Nächste walk it. */
export function DocumentMails({
  document,
  state,
  href,
}: {
  document: DocumentDetail;
  state: DocumentMailState;
  href: (state: DocumentMailState) => string;
}) {
  const list = documentMailList(document.id, state);
  const page = useMailPage(toListParams(list));

  return (
    <Card className={styles.card} aria-labelledby="document-mails-title">
      <div className={styles.head}>
        <CardTitle id="document-mails-title">
          Wer hat dieses Dokument wann an wen geschickt
        </CardTitle>
        <Link
          to={documentMailsHref(document.id)}
          className={styles.all}
          title="In der Mailliste: weiter filtern oder als CSV exportieren"
        >
          Alle Mails mit diesem Dokument
        </Link>
      </div>
      {page.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Mails werden geladen" />
        </div>
      ) : page.isError ? (
        page.error instanceof ApiError && page.error.code === "page_too_far" ? (
          <PageTooFar {...edgePages(state, href)} />
        ) : page.error instanceof ApiError && page.error.code === "invalid_cursor" ? (
          <ErrorState
            title="Diese Seite gibt es nicht mehr."
            actions={
              <Link to={href({ ...state, ...FIRST_PAGE })} className={buttonClass()}>
                Zur ersten Seite
              </Link>
            }
          >
            Der Link verweist auf eine veraltete Seite der Liste.
          </ErrorState>
        ) : (
          <ErrorState
            title="Die Mails konnten nicht geladen werden."
            actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        )
      ) : page.data.items.length === 0 ? (
        <EmptyState title="Keine Mails">
          Die Mails mit diesem Dokument sind nur als Duplikate im Archiv.
        </EmptyState>
      ) : (
        <>
          <MailTable
            items={page.data.items}
            columns={COLUMNS}
            detailSearch={listSearch(list).toString()}
            mboxPath={noPath}
            stale={page.isPlaceholderData}
          />
          <div className={styles.paging}>
            <Pagination
              {...listPagination(
                state,
                page.data,
                page.data.items.length,
                { count: document.mails, exact: true },
                href,
              )}
            />
          </div>
        </>
      )}
    </Card>
  );
}
