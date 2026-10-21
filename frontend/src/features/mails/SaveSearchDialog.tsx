import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useCreateSearch, useResearch } from "../../api/queries";
import { NAME_LIMIT } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Dialog } from "../persons/Dialog";
import styles from "./SaveSearchDialog.module.css";

/** "Suche speichern" (D59): the list's query string under a name, optionally in an Akte. It is
 *  run anew whenever it is opened. */
export function SaveSearchDialog({
  query,
  suggestedName,
  onClose,
}: {
  /** Query string of /mails without cursor and page. */
  query: string;
  suggestedName: string;
  onClose: () => void;
}) {
  const create = useCreateSearch();
  const research = useResearch();
  const [name, setName] = useState(suggestedName.slice(0, NAME_LIMIT));
  const [collection, setCollection] = useState("");
  const saved = create.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || create.isPending) return;
    create.mutate({
      name: name.trim(),
      query,
      collection_id: collection ? Number(collection) : null,
    });
  }

  if (saved) {
    const akte = research.data?.collections.find((other) => other.id === saved.collection_id);
    return (
      <Dialog title="Suche gespeichert" onClose={onClose}>
        <p className={styles.text}>
          „{saved.name}“ steht {akte ? `in der Akte „${akte.name}“` : "unter Akten"} und sucht bei
          jedem Öffnen neu.
        </p>
        <div className={styles.foot}>
          <Button onClick={onClose}>Schließen</Button>
          <Link
            to={saved.collection_id ? `/akten/${saved.collection_id}` : "/akten"}
            className={buttonClass("primary")}
          >
            In Akten ansehen
          </Link>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Suche speichern" onClose={onClose}>
      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor="search-name" className={styles.label}>
          Name
        </label>
        <input
          id="search-name"
          className={styles.input}
          value={name}
          maxLength={NAME_LIMIT}
          onChange={(event) => setName(event.target.value)}
        />
        <label htmlFor="search-collection" className={styles.label}>
          Akte (optional)
        </label>
        <select
          id="search-collection"
          className={styles.input}
          value={collection}
          onChange={(event) => setCollection(event.target.value)}
        >
          <option value="">Keine Akte</option>
          {research.data?.collections.map((other) => (
            <option key={other.id} value={other.id}>
              {other.name}
            </option>
          ))}
        </select>
        <p className={styles.text}>
          Gespeichert werden Suchtext, Filter und Sortierung; die Treffer werden bei jedem Öffnen
          neu gesucht.
        </p>
        {create.isError && (
          <p className={styles.error} role="alert">
            Die Suche wurde nicht gespeichert. Bitte noch einmal versuchen.
          </p>
        )}
        <div className={styles.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
            Speichern
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
