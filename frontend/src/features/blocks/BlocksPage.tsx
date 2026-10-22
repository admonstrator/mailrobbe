import { HiddenTabs } from "../hiding/HiddenTabs";
import styles from "./BlocksPage.module.css";

/** "Ausgeblendet · Standardblöcke" (D227). Contract placeholder: milestone 18 fills it. */
export function BlocksPage() {
  return (
    <main className={styles.page}>
      <title>Standardblöcke · Mailrobbe</title>
      <HiddenTabs />
      <p>Die Standardblöcke entstehen gerade.</p>
    </main>
  );
}
