import { useEffect, useState } from "react";

import styles from "./AiBusy.module.css";

/** "2:14": minutes and seconds since iso. */
export function since(iso: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** A running AI task (D345, D348): a moving bar and what is under way, with "KI rechnet seit
 *  2:14 Min." ticking every second from the task's start, else from its queuing. */
export function AiBusy({ what, from }: { what: string; from?: string | null }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (!from) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [from]);
  return (
    <div className={styles.busy} role="status">
      <div className={styles.bar} aria-hidden="true">
        <span />
      </div>
      {from ? `${what} · KI rechnet seit ${since(from, now)} Min.` : what}
    </div>
  );
}
