import { useId, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import { Button } from "../../components/Button";
import { cx } from "../../lib/cx";
import forms from "./forms.module.css";
import styles from "./InlineEdit.module.css";
import { researchErrorText } from "./labels";

/** A text with a button that turns it into a field in place. Enter saves (Strg+Enter in a
 *  multi-line field), Escape cancels; an unchanged text is not sent. Quiet shows a pencil only
 *  while the pointer or the focus is on the text; a change of editRequest opens the field from
 *  elsewhere, e.g. a menu. */
export function InlineEdit({
  value,
  label,
  multiline = false,
  maxLength,
  required = false,
  onSave,
  quiet = false,
  editRequest = 0,
  children,
}: {
  value: string;
  /** What is edited, e.g. "Name"; the button reads "<label> bearbeiten". */
  label: string;
  multiline?: boolean;
  maxLength: number;
  required?: boolean;
  onSave: (value: string) => Promise<unknown>;
  quiet?: boolean;
  editRequest?: number;
  children: ReactNode;
}) {
  const id = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);

  // A new request opens the field, as a change of state during render (no effect).
  const [request, setRequest] = useState(editRequest);
  if (request !== editRequest) {
    setRequest(editRequest);
    setDraft(value);
    setError(null);
  }

  if (draft === null) {
    return (
      <div className={cx(styles.view, quiet && styles.quiet)}>
        <div className={styles.content}>{children}</div>
        <Button
          variant="link"
          size="xs"
          className={styles.edit}
          aria-label={`${label} bearbeiten`}
          title={quiet ? `${label} bearbeiten` : undefined}
          onClick={() => {
            setDraft(value);
            setError(null);
          }}
        >
          {quiet ? <PencilIcon /> : "Bearbeiten"}
        </Button>
      </div>
    );
  }

  const text = draft.trim();
  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (text === value.trim()) {
      setDraft(null);
      return;
    }
    setSaving(true);
    try {
      await onSave(text);
      setDraft(null);
    } catch (failure) {
      setError(failure as Error);
    } finally {
      setSaving(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement | HTMLTextAreaElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setDraft(null);
    } else if (multiline && event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void save();
    }
  }

  const field = {
    id,
    value: draft,
    maxLength,
    autoFocus: true,
    onKeyDown,
    onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
  };
  return (
    <form className={styles.form} onSubmit={(event) => void save(event)}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      {multiline ? (
        <textarea className={forms.textarea} {...field} />
      ) : (
        <input className={forms.input} autoComplete="off" {...field} />
      )}
      <div className={styles.buttons}>
        <Button type="submit" variant="primary" size="sm" disabled={saving || (required && !text)}>
          Speichern
        </Button>
        <Button size="sm" onClick={() => setDraft(null)}>
          Abbrechen
        </Button>
      </div>
      {error && (
        <p className={forms.error} role="alert">
          {researchErrorText(error)}
        </p>
      )}
    </form>
  );
}

function PencilIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 20h4L19 9l-4-4L4 16z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </svg>
  );
}
