import { HiddenTabs } from "./HiddenTabs";
import styles from "./HidingPage.module.css";

/** "Ausgeblendet · Ausblendregeln" (D223). Contract placeholder: milestone 18 fills it. */
export function HidingPage() {
  return (
    <main className={styles.page}>
      <title>Ausblendregeln · Mailrobbe</title>
      <HiddenTabs />
      <p>Die Ausblendregeln entstehen gerade.</p>
    </main>
  );
}
