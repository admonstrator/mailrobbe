import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { useCreateCollection } from "../../api/queries";
import { DESCRIPTION_LIMIT, NAME_LIMIT, type CollectionInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { HelpTip } from "../../components/PageHead";
import { EmptyState } from "../../components/EmptyState";
import { formatDateTime } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./AktenScreen.module.css";
import forms from "./forms.module.css";
import { mailCount, researchErrorText } from "./labels";

/** The Akten tab: every Akte, last changed first (D58), and "Neue Akte". */
export function CollectionList({ collections }: { collections: CollectionInfo[] }) {
  const [creating, setCreating] = useState(false);
  return (
    <>
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Eine Akte sammelt die Mails zu einer Geschichte oder Frage.
          <HelpTip text="Mit Beschreibung, gespeicherten Suchen, Notizen und Export." />
        </p>
        <Button variant="primary" onClick={() => setCreating(true)}>
          Neue Akte
        </Button>
      </div>
      <div className={styles.listCard}>
        {collections.length === 0 ? (
          <EmptyState title="Noch keine Akte">
            Eine Akte entsteht hier oder in der Mailliste, wenn Mails einer neuen Akte zugeordnet
            werden.
          </EmptyState>
        ) : (
          <ul className={styles.list}>
            {collections.map((collection) => (
              <li key={collection.id} className={styles.item}>
                <div className={styles.itemMain}>
                  <Link to={`/akten/${collection.id}`} className={styles.itemTitle}>
                    {collection.name}
                  </Link>
                  {collection.description && (
                    <p className={styles.excerpt}>{collection.description}</p>
                  )}
                </div>
                <div className={styles.itemMeta}>
                  <span className={styles.count}>{mailCount(collection.mails)}</span>
                  <span>
                    geändert {formatDateTime(collection.updated_at)}
                    {collection.created_by && ` · angelegt von ${collection.created_by}`}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      {creating && <NewCollectionDialog onClose={() => setCreating(false)} />}
    </>
  );
}

/** Name and description of a new Akte; the Akte opens once it is created. */
function NewCollectionDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateCollection();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const collection = await create.mutateAsync({
        name: name.trim(),
        description: description.trim(),
      });
      void navigate(`/akten/${collection.id}`);
    } catch {
      // shown in the form
    }
  }

  return (
    <Dialog title="Neue Akte" onClose={onClose}>
      <form className={forms.form} onSubmit={(event) => void onSubmit(event)}>
        <label className={forms.field}>
          <span className={forms.label}>Name</span>
          <input
            className={forms.input}
            value={name}
            maxLength={NAME_LIMIT}
            required
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className={forms.field}>
          <span className={forms.label}>Beschreibung (optional)</span>
          <textarea
            className={forms.textarea}
            value={description}
            maxLength={DESCRIPTION_LIMIT}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {create.isError && (
          <p className={forms.error} role="alert">
            {researchErrorText(create.error)}
          </p>
        )}
        <div className={forms.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
            Akte anlegen
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
