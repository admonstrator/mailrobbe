import type { ReactNode } from "react";
import { NavLink } from "react-router";

import { cx } from "../../lib/cx";
import { PageHead } from "../import/PageHead";
import styles from "./HiddenTabs.module.css";

/** The page "Ausgeblendet" (D223, D227) as a page of D334: the head with the part's explanation
 *  behind its help and the part's actions, then the links between its two parts, hide rules and
 *  standard blocks, each a route of its own, drawn as tabs. */
export function HiddenTabs({ help, actions }: { help?: string; actions?: ReactNode }) {
  const link = ({ isActive }: { isActive: boolean }) => cx(styles.tab, isActive && styles.active);
  return (
    <>
      <PageHead
        title="Ausgeblendet"
        sub="Was Mailliste, Suche und Zahlen auslassen; im Archiv bleibt alles."
        help={help}
        actions={actions}
      />
      <nav aria-label="Ausgeblendet" className={styles.tabs}>
        <NavLink to="/ausgeblendet" end className={link}>
          Ausblendregeln
        </NavLink>
        <NavLink to="/ausgeblendet/bloecke" className={link}>
          Standardblöcke
        </NavLink>
      </nav>
    </>
  );
}
