import type { ComponentProps } from "react";

import { cx } from "../lib/cx";
import styles from "./Button.module.css";

type Variant = "default" | "primary" | "outline" | "link";
type Size = "md" | "sm" | "xs";

/** The button look, also for links that act as buttons (downloads, export). */
export function buttonClass(variant: Variant = "default", size: Size = "md"): string {
  return cx(styles.button, styles[variant], styles[size]);
}

export function Button({
  variant,
  size,
  className,
  type = "button",
  ...rest
}: ComponentProps<"button"> & { variant?: Variant; size?: Size }) {
  return <button type={type} className={cx(buttonClass(variant, size), className)} {...rest} />;
}
