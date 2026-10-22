import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import { PAGE_SIZES } from "../lib/paging";
import { buttonClass } from "./Button";
import { ErrorState } from "./ErrorState";
import styles from "./Pagination.module.css";

/** The numbered pages of a list (D193): 1 to pages, more when the list goes on after them. */
export interface PageNumbers {
  /** The page shown; null when its number is not known (a last page read from the end). */
  current: number | null;
  pages: number;
  more: boolean;
  href: (page: number) => string;
}

export interface PaginationProps {
  range: ReactNode;
  /** Zurück and Weiter; null where there is no such page. */
  prev: string | null;
  next: string | null;
  /** The first and the last page; null on it, left out to show no such step. */
  first?: string | null;
  last?: string | null;
  /** Page numbers around the current one and the field "Seite" to jump to one. */
  numbers?: PageNumbers;
  /** The page size and the first page at another one. */
  size?: { limit: number; href: (limit: number) => string };
}

/** Range text with Zurück/Weiter links (D19), and optionally the first and last page, page
 *  numbers, a jump to a page and the page size (D193). Every target is a link; the page number
 *  and the page size are typed or chosen and then followed. */
export function Pagination({ range, prev, next, first, last, numbers, size }: PaginationProps) {
  return (
    <nav className={styles.pagination} aria-label="Seiten">
      <span>{range}</span>
      <div className={styles.steps}>
        {first !== undefined &&
          step(
            first,
            <>
              « Erste <span className={styles.word}>Seite</span>
            </>,
          )}
        {step(prev, "‹ Zurück")}
        {numbers && <Numbers {...numbers} />}
        {step(next, "Weiter ›")}
        {last !== undefined &&
          step(
            last,
            <>
              Letzte <span className={styles.word}>Seite</span> »
            </>,
          )}
      </div>
      {(numbers || size) && (
        <div className={styles.tools}>
          {numbers && <Jump {...numbers} />}
          {size && <PageSize {...size} />}
        </div>
      )}
    </nav>
  );
}

function step(to: string | null, text: ReactNode) {
  return to === null ? (
    <span className={buttonClass("default", "sm")} aria-disabled="true">
      {text}
    </span>
  ) : (
    <Link to={to} className={buttonClass("default", "sm")}>
      {text}
    </Link>
  );
}

/** The pages shown: the first, the last numbered one and the neighbours of the current one, in
 *  order; null for a gap of more than one page (a single page is shown instead of a gap). */
export function pageWindow(current: number | null, pages: number): (number | null)[] {
  const shown = new Set([1, pages]);
  if (current !== null) {
    for (const page of [current - 1, current, current + 1]) {
      if (page >= 1 && page <= pages) shown.add(page);
    }
  }
  const sorted = [...shown].sort((a, b) => a - b);
  const window: (number | null)[] = [];
  for (const page of sorted) {
    const before = window.at(-1);
    if (typeof before === "number" && page - before === 2) window.push(page - 1);
    else if (typeof before === "number" && page - before > 2) window.push(null);
    window.push(page);
  }
  return window;
}

function Numbers({ current, pages, more, href }: PageNumbers) {
  const window = pageWindow(current, pages);
  return (
    <span className={styles.numbers}>
      {window.map((page, index) =>
        page === null ? (
          <span key={`gap-${index}`} className={styles.gap} aria-hidden="true">
            …
          </span>
        ) : (
          <Link
            key={page}
            to={href(page)}
            className={buttonClass(page === current ? "outline" : "default", "sm")}
            aria-label={`Seite ${page}`}
            aria-current={page === current ? "page" : undefined}
          >
            {page}
          </Link>
        ),
      )}
      {more && (
        <span className={styles.gap} aria-hidden="true">
          …
        </span>
      )}
    </span>
  );
}

/** The field "Seite": Enter or Los follows the page typed, at most the last numbered one unless
 *  the list goes on after it. */
function Jump({ current, pages, more, href }: PageNumbers) {
  const navigate = useNavigate();
  const [typed, setTyped] = useState("");
  return (
    <form
      className={styles.jump}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const page = Number(typed);
        if (!Number.isInteger(page) || page < 1) return;
        setTyped("");
        void navigate(href(more ? page : Math.min(page, pages)));
      }}
    >
      <label className={styles.field}>
        Seite
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={more ? undefined : pages}
          value={typed}
          placeholder={current === null ? undefined : String(current)}
          onChange={(event) => setTyped(event.target.value)}
        />
      </label>
      <button type="submit" className={buttonClass("default", "sm")}>
        Los
      </button>
    </form>
  );
}

function PageSize({ limit, href }: { limit: number; href: (limit: number) => string }) {
  const navigate = useNavigate();
  const sizes = PAGE_SIZES.includes(limit)
    ? PAGE_SIZES
    : [...PAGE_SIZES, limit].sort((a, b) => a - b);
  return (
    <label className={styles.field}>
      Pro Seite
      <select value={limit} onChange={(event) => void navigate(href(Number(event.target.value)))}>
        {sizes.map((size) => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
    </label>
  );
}

/** A jump that did not answer within the count budget (page_too_far, D193): the first and the
 *  last page are always reached at once, and Zurück and Weiter go on from there. */
export function PageTooFar({ first, last }: { first: string; last: string }) {
  return (
    <ErrorState
      title="Diese Seite ist zu weit entfernt."
      actions={
        <>
          <Link to={first} className={buttonClass()}>
            Erste Seite
          </Link>
          <Link to={last} className={buttonClass()}>
            Letzte Seite
          </Link>
        </>
      }
    >
      Mailrobbe hat sie nicht rechtzeitig gefunden. Die erste und die letzte Seite sind sofort da,
      von dort geht es mit Zurück und Weiter.
    </ErrorState>
  );
}
