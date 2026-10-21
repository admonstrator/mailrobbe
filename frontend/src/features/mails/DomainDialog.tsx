import { useEffect, useRef, useState } from "react";

import { DOMAIN_SEARCH_LIMIT, useSenderDomains } from "../../api/queries";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import styles from "./DomainDialog.module.css";

/** All sender domains with a search field; ticking one changes the list right away. */
export function DomainDialog({
  selected,
  onToggle,
  onClose,
}: {
  selected: string[];
  onToggle: (domain: string, checked: boolean) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim().toLowerCase(), 250);
  const domains = useSenderDomains(q, true);

  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
  }, []);

  return (
    <dialog
      ref={dialog}
      className={styles.dialog}
      aria-labelledby="domain-dialog-title"
      onClose={onClose}
      onClick={(event) => event.target === dialog.current && dialog.current?.close()}
    >
      <div className={styles.body}>
        <h2 id="domain-dialog-title" className={styles.title}>
          Absender-Domains
        </h2>
        <label htmlFor="domain-search" className="sr-only">
          Domain suchen
        </label>
        <input
          id="domain-search"
          type="search"
          className={styles.search}
          placeholder="Domain suchen …"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        <div className={styles.list}>
          {domains.isPending && <Spinner />}
          {domains.isError && (
            <p className={styles.note}>Die Domains konnten nicht geladen werden.</p>
          )}
          {domains.data?.length === 0 && <p className={styles.note}>Keine Domain gefunden.</p>}
          {domains.data?.map(({ domain, mails }) => (
            <Checkbox
              key={domain}
              checked={selected.includes(domain)}
              onChange={(checked) => onToggle(domain, checked)}
              count={mails}
            >
              {domain}
            </Checkbox>
          ))}
          {domains.data?.length === DOMAIN_SEARCH_LIMIT && (
            <p className={styles.note}>
              Die ersten {formatNumber(DOMAIN_SEARCH_LIMIT)} Domains; die Suche grenzt weiter ein.
            </p>
          )}
        </div>
        <div className={styles.foot}>
          <span>{selected.length > 0 && `${formatNumber(selected.length)} ausgewählt`}</span>
          <Button variant="primary" onClick={() => dialog.current?.close()}>
            Fertig
          </Button>
        </div>
      </div>
    </dialog>
  );
}
