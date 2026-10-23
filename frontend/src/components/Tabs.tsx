import type { KeyboardEvent, ReactNode } from "react";

import { cx } from "../lib/cx";
import styles from "./Tabs.module.css";

export interface TabItem<T extends string> {
  id: T;
  label: string;
  disabled?: boolean;
  title?: string;
  /** A count shown as a small badge after the label, such as the files of a tab. */
  count?: number | string;
}

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`;
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`;

/** A tab bar (WAI-ARIA tabs: arrow keys move between tabs) underlined like the mockup of D332;
 *  end is shown on its right. */
export function Tabs<T extends string>({
  items,
  active,
  onSelect,
  idPrefix,
  label,
  end,
}: {
  items: TabItem<T>[];
  active: T;
  onSelect: (id: T) => void;
  idPrefix: string;
  label: string;
  end?: ReactNode;
}) {
  const enabled = items.filter((item) => !item.disabled);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = enabled.findIndex((item) => item.id === active);
    const next = enabled[(index + step + enabled.length) % enabled.length];
    onSelect(next.id);
    document.getElementById(tabId(idPrefix, next.id))?.focus();
  }

  return (
    <div className={styles.bar}>
      <div role="tablist" aria-label={label} className={styles.list}>
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            id={tabId(idPrefix, item.id)}
            aria-controls={panelId(idPrefix, item.id)}
            aria-selected={item.id === active}
            tabIndex={item.id === active ? 0 : -1}
            disabled={item.disabled}
            title={item.title}
            className={cx(styles.tab, item.id === active && styles.active)}
            onClick={() => onSelect(item.id)}
            onKeyDown={onKeyDown}
          >
            {item.label}
            {item.count !== undefined && <span className={styles.count}>{item.count}</span>}
          </button>
        ))}
      </div>
      {end && <div className={styles.end}>{end}</div>}
    </div>
  );
}

/** The attributes of the panel that belongs to tab id. */
export function tabPanelProps(idPrefix: string, id: string) {
  return { role: "tabpanel", id: panelId(idPrefix, id), "aria-labelledby": tabId(idPrefix, id) };
}
