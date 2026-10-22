import { HiddenTabs } from "../hiding/HiddenTabs";
import styles from "./BlocksPage.module.css";

/** One standard block (D227). Contract placeholder: milestone 18 fills it. */
export function BlockDetailPage() {
  return (
    <main className={styles.page}>
      <title>Standardblock · Mailrobbe</title>
      <HiddenTabs />
      <p>Die Seite eines Standardblocks entsteht gerade.</p>
    </main>
  );
}
