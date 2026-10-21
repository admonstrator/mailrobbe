import { useId, useState, type KeyboardEvent } from "react";
import { Link } from "react-router";

import type { TagColor } from "../../api/types";
import { TAG_PALETTE } from "../../lib/research";
import styles from "./LinkField.module.css";

/** A tag or an Akte as the field shows it. */
export interface LinkItem {
  id: number;
  name: string;
  color?: TagColor;
}

type Option = { item: LinkItem } | { create: string };

/** Suggestions listed at most. */
const SUGGESTIONS = 8;

const fold = (name: string) => name.trim().toLocaleLowerCase("de");

/** The tags or Akten of a mail: chips that remove one, and a field that adds an existing one
 *  from its suggestions or creates one under the typed name. Enter takes the highlighted
 *  option; without one it is the item of exactly that name, else the first suggestion, else a
 *  new one, so a shared vocabulary does not split into near-duplicates by accident. */
export function LinkField({
  label,
  addLabel,
  removeLabel,
  createLabel,
  items,
  known,
  maxLength,
  href,
  onAdd,
  onRemove,
  onCreate,
}: {
  label: string;
  addLabel: string;
  removeLabel: string;
  createLabel: (name: string) => string;
  /** Linked to the mail now. */
  items: LinkItem[];
  /** Every one that exists, for the suggestions. */
  known: LinkItem[];
  maxLength: number;
  href?: (id: number) => string;
  onAdd: (id: number) => void;
  onRemove: (id: number) => void;
  onCreate: (name: string) => void;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const listId = useId();

  const name = text.trim();
  const linked = new Set(items.map((item) => item.id));
  const exact = known.find((item) => fold(item.name) === fold(name));
  const options: Option[] = known
    .filter((item) => !linked.has(item.id) && fold(item.name).includes(fold(name)))
    .slice(0, SUGGESTIONS)
    .map((item) => ({ item }));
  if (name && !exact) options.push({ create: name });
  // What Enter does without a highlighted option is highlighted too.
  const fallback = !name
    ? -1
    : exact
      ? options.findIndex((option) => "item" in option && option.item === exact)
      : 0;
  const current = active ?? fallback;
  const shown = open && options.length > 0;

  function choose(option: Option) {
    if ("item" in option) onAdd(option.item.id);
    else onCreate(option.create);
    setText("");
    setActive(null);
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      const count = options.length;
      if (count === 0) return;
      setActive(current < 0 ? (step > 0 ? 0 : count - 1) : (current + step + count) % count);
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (current >= 0) choose(options[current]);
      else if (exact) setText(""); // linked already
    } else if (event.key === "Escape" && shown) {
      event.preventDefault();
      setOpen(false);
    }
  }

  return (
    <div className={styles.field}>
      <span className={styles.label}>{label}</span>
      {items.length > 0 && (
        <ul className={styles.chips} aria-label={label}>
          {items.map((item) => (
            <li
              key={item.id}
              className={item.color ? styles.tag : styles.chip}
              style={
                item.color && {
                  background: TAG_PALETTE[item.color].background,
                  borderColor: TAG_PALETTE[item.color].border,
                  color: TAG_PALETTE[item.color].text,
                }
              }
            >
              {href ? <Link to={href(item.id)}>{item.name}</Link> : item.name}
              <button
                type="button"
                className={styles.remove}
                aria-label={`${removeLabel}: ${item.name}`}
                onClick={() => onRemove(item.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className={styles.combo}>
        <input
          type="text"
          role="combobox"
          aria-label={addLabel}
          aria-autocomplete="list"
          aria-expanded={shown}
          aria-controls={listId}
          aria-activedescendant={shown && current >= 0 ? `${listId}-${current}` : undefined}
          className={styles.input}
          placeholder={`${addLabel} …`}
          value={text}
          maxLength={maxLength}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) => {
            setText(event.target.value);
            setActive(null);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {shown && (
          <ul
            id={listId}
            role="listbox"
            aria-label={`Vorschläge: ${label}`}
            className={styles.options}
          >
            {options.map((option, index) => (
              <li
                key={"item" in option ? option.item.id : "create"}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === current}
                className={styles.option}
                // Keeps the focus in the field, which would close the list before the click.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option)}
              >
                {"item" in option ? (
                  <>
                    {option.item.color && (
                      <span
                        className={styles.dot}
                        style={{ background: TAG_PALETTE[option.item.color].text }}
                        aria-hidden="true"
                      />
                    )}
                    {option.item.name}
                  </>
                ) : (
                  <span className={styles.create}>{createLabel(option.create)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
