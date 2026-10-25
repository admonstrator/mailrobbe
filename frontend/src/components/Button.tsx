import type { ComponentProps } from "react";

import { cx } from "../lib/cx";
import styles from "./Button.module.css";
import { SparklesIcon } from "./icons";

/** "ai": light blue with the sparkles, for every action of the AI (D352). */
type Variant = "default" | "primary" | "outline" | "link" | "ai";
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
  children,
  ...rest
}: ComponentProps<"button"> & { variant?: Variant; size?: Size }) {
  return (
    <button type={type} className={cx(buttonClass(variant, size), className)} {...rest}>
      {variant === "ai" && <SparklesIcon size={size === "md" || !size ? 16 : 14} />}
      {children}
    </button>
  );
}
