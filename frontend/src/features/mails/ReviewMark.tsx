import type { ReviewKey } from "../../api/types";
import { cx } from "../../lib/cx";
import { REVIEW_LABELS } from "../../lib/research";
import styles from "./ReviewMark.module.css";

/** The review status as a small coloured bar (D55): relevant stands out, the others stay calm,
 *  and unreviewed is an empty place of the same width, so the subjects line up. The label is
 *  its tooltip and what screen readers hear, unless the mark sits next to the label anyway. */
export function ReviewMark({
  status,
  decorative = false,
}: {
  status: ReviewKey;
  decorative?: boolean;
}) {
  const label = REVIEW_LABELS[status];
  return (
    <span
      className={cx(styles.mark, styles[status])}
      {...(decorative || status === "unreviewed"
        ? { "aria-hidden": true }
        : { role: "img", "aria-label": `Status: ${label}`, title: label })}
    />
  );
}
