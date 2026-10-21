import type { ComponentProps, ReactNode } from "react";

import { cx } from "../lib/cx";
import styles from "./Card.module.css";

/** The white, bordered surface every block of a screen sits on. "side" is the narrower padding
 *  of the detail view's right column. */
export function Card({
  variant = "main",
  className,
  ...rest
}: ComponentProps<"section"> & { variant?: "main" | "side" }) {
  return <section className={cx(styles.card, styles[variant], className)} {...rest} />;
}

/** A card heading: "plain" for the main column, "caps" for the small uppercase side headings. */
export function CardTitle({
  variant = "plain",
  id,
  children,
}: {
  variant?: "plain" | "caps";
  id?: string;
  children: ReactNode;
}) {
  return (
    <h2 id={id} className={styles[variant]}>
      {children}
    </h2>
  );
}
