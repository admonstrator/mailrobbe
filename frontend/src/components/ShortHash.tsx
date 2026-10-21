import { useEffect, useRef, useState } from "react";

import { Button } from "./Button";
import styles from "./ShortHash.module.css";

const SHOWN = 16; // hex digits, as in a permalink (D61)

/** A SHA-256 shortened to its first digits, the whole value in the tooltip, and with copy a
 *  button that copies it whole. Without a clipboard (plain HTTP on another host) the button
 *  shows the whole value selected instead. */
export function ShortHash({ hash, copy = false }: { hash: string; copy?: boolean }) {
  const value = useRef<HTMLElement>(null);
  const [state, setState] = useState<"copied" | "selected" | null>(null);
  useEffect(() => {
    if (state === "copied") {
      const timer = setTimeout(() => setState(null), 2000);
      return () => clearTimeout(timer);
    }
    if (state === "selected" && value.current) {
      window.getSelection()?.selectAllChildren(value.current);
    }
  }, [state]);

  return (
    <span className={styles.hash}>
      <code ref={value} className={styles.value} title={hash}>
        {state === "selected" || hash.length <= SHOWN ? hash : `${hash.slice(0, SHOWN)}…`}
      </code>
      {copy && (
        <Button
          variant="link"
          size="xs"
          aria-label={`SHA-256 ${hash} kopieren`}
          onClick={() => {
            if (!navigator.clipboard) return setState("selected");
            navigator.clipboard.writeText(hash).then(
              () => setState("copied"),
              () => setState("selected"),
            );
          }}
        >
          Kopieren
        </Button>
      )}
      {copy && (
        <span className={styles.status} role="status">
          {state === "copied" ? "Kopiert" : state === "selected" ? "Mit Strg+C kopieren" : ""}
        </span>
      )}
    </span>
  );
}
