import type { ReactNode } from "react";

import type { TagColor } from "../../api/types";
import { TAG_PALETTE } from "../../lib/research";
import styles from "./ColorChip.module.css";

/** A tag or theme name in its colour (D57). */
export function ColorChip({ color, children }: { color: TagColor; children: ReactNode }) {
  const { background, text, border } = TAG_PALETTE[color];
  return (
    <span className={styles.chip} style={{ background, color: text, borderColor: border }}>
      {children}
    </span>
  );
}

/** The colour alone, as a dot. */
export function ColorDot({ color }: { color: TagColor }) {
  return <span className={styles.dot} style={{ background: TAG_PALETTE[color].text }} />;
}
