import { NavLink } from "react-router";

import { cx } from "../../lib/cx";
import styles from "./HiddenTabs.module.css";

/** The page "Ausgeblendet" (D223, D227): its title and the links between its two parts, hide
 *  rules and standard blocks, each a route of its own. */
export function HiddenTabs() {
  const link = ({ isActive }: { isActive: boolean }) => cx(styles.tab, isActive && styles.active);
  return (
    <div className={styles.head}>
      <h1 className={styles.title}>Ausgeblendet</h1>
      <nav aria-label="Ausgeblendet" className={styles.tabs}>
        <NavLink to="/ausgeblendet" end className={link}>
          Ausblendregeln
        </NavLink>
        <NavLink to="/ausgeblendet/bloecke" className={link}>
          Standardblöcke
        </NavLink>
      </nav>
    </div>
  );
}
