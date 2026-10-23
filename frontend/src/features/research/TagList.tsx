import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useCreateTag, useDeleteTag, useUpdateTag } from "../../api/queries";
import {
  DESCRIPTION_LIMIT,
  TAG_NAME_LIMIT,
  type TagColor,
  type TagInfo,
  type TagUpdate,
} from "../../api/types";
import { Button } from "../../components/Button";
import { HelpTip } from "../../components/PageHead";
import { EmptyState } from "../../components/EmptyState";
import { TAG_COLORS, TAG_COLOR_LABELS, TAG_PALETTE } from "../../lib/research";
import { Dialog } from "../persons/Dialog";
import styles from "./AktenScreen.module.css";
import { ColorChip } from "./ColorChip";
import { ConfirmDialog } from "./ConfirmDialog";
import forms from "./forms.module.css";
import { mailCount, researchErrorText, tagMailsHref } from "./labels";

/** The Schlagworte tab (D57): every tag with colour, description and mail count; create, edit
 *  and delete. */
export function TagList({ tags }: { tags: TagInfo[] }) {
  const [editing, setEditing] = useState<TagInfo | "new" | null>(null);
  const [deleting, setDeleting] = useState<TagInfo | null>(null);
  const remove = useDeleteTag();

  return (
    <>
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Schlagworte ordnen Mails nach Themen und Fragen.
          <HelpTip text="Eine Mail kann beliebig viele Schlagworte tragen." />
        </p>
        <Button variant="primary" onClick={() => setEditing("new")}>
          Neues Schlagwort
        </Button>
      </div>
      <div className={styles.listCard}>
        {tags.length === 0 ? (
          <EmptyState title="Noch kein Schlagwort">
            Schlagworte entstehen hier, in der Mailliste oder mit dem Themen-Startset.
          </EmptyState>
        ) : (
          <ul className={styles.list}>
            {tags.map((tag) => (
              <li key={tag.id} className={styles.item}>
                <div className={styles.itemMain}>
                  <span>
                    <ColorChip color={tag.color}>{tag.name}</ColorChip>
                  </span>
                  {tag.description && <p className={styles.excerpt}>{tag.description}</p>}
                </div>
                <div className={styles.itemActions}>
                  <Link to={tagMailsHref(tag.id)} className={styles.count}>
                    {mailCount(tag.mails)}
                  </Link>
                  <Button
                    size="sm"
                    onClick={() => setEditing(tag)}
                    aria-label={`„${tag.name}“ bearbeiten`}
                  >
                    Bearbeiten
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => {
                      remove.reset();
                      setDeleting(tag);
                    }}
                    aria-label={`„${tag.name}“ löschen`}
                  >
                    Löschen
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      {editing && (
        <TagDialog tag={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      )}
      {deleting && (
        <ConfirmDialog
          title="Schlagwort löschen"
          confirmLabel="Löschen"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          Das Schlagwort „{deleting.name}“ wird gelöscht und{" "}
          {deleting.mails === 0
            ? "trägt keine Mail."
            : `von ${mailCount(deleting.mails)} entfernt.`}{" "}
          Die Mails selbst, ihre Notizen und Akten bleiben.
        </ConfirmDialog>
      )}
    </>
  );
}

/** Create a tag (tag null) or change one: name, colour, description. Only what changed is
 *  sent. */
function TagDialog({ tag, onClose }: { tag: TagInfo | null; onClose: () => void }) {
  const create = useCreateTag();
  const update = useUpdateTag();
  const [name, setName] = useState(tag?.name ?? "");
  const [color, setColor] = useState<TagColor>(tag?.color ?? "blue");
  const [description, setDescription] = useState(tag?.description ?? "");
  const write = tag ? update : create;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = { name: name.trim(), color, description: description.trim() };
    try {
      if (tag) {
        const changed: TagUpdate = {};
        if (values.name !== tag.name) changed.name = values.name;
        if (values.color !== tag.color) changed.color = values.color;
        if (values.description !== tag.description) changed.description = values.description;
        if (Object.keys(changed).length) await update.mutateAsync({ id: tag.id, ...changed });
      } else {
        await create.mutateAsync(values);
      }
      onClose();
    } catch {
      // shown in the form
    }
  }

  return (
    <Dialog title={tag ? "Schlagwort bearbeiten" : "Neues Schlagwort"} onClose={onClose}>
      <form className={forms.form} onSubmit={(event) => void onSubmit(event)}>
        <label className={forms.field}>
          <span className={forms.label}>Name</span>
          <input
            className={forms.input}
            value={name}
            maxLength={TAG_NAME_LIMIT}
            required
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <fieldset className={forms.field}>
          <legend className={forms.label}>Farbe</legend>
          <div className={forms.colors}>
            {TAG_COLORS.map((option) => {
              const palette = TAG_PALETTE[option];
              return (
                <label
                  key={option}
                  className={forms.color}
                  style={{
                    background: palette.background,
                    color: palette.text,
                    borderColor: palette.border,
                  }}
                >
                  <input
                    type="radio"
                    name="tag-color"
                    value={option}
                    checked={color === option}
                    onChange={() => setColor(option)}
                  />
                  {TAG_COLOR_LABELS[option]}
                </label>
              );
            })}
          </div>
        </fieldset>
        <label className={forms.field}>
          <span className={forms.label}>Beschreibung (optional)</span>
          <textarea
            className={forms.textarea}
            value={description}
            maxLength={DESCRIPTION_LIMIT}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        {write.isError && (
          <p className={forms.error} role="alert">
            {researchErrorText(write.error)}
          </p>
        )}
        <div className={forms.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" disabled={!name.trim() || write.isPending}>
            {tag ? "Speichern" : "Schlagwort anlegen"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
