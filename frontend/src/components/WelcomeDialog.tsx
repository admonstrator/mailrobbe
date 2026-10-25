import { useState } from "react";

import { Dialog } from "../features/persons/Dialog";
import { markWelcomeSeen, welcomeSeen } from "../lib/welcome";
import { Button, buttonClass } from "./Button";
import styles from "./WelcomeDialog.module.css";

const SUPPORT_LINKS = [
  { name: "GitHub Sponsors", href: "https://github.com/sponsors/admonstrator" },
  { name: "Buy Me a Coffee", href: "https://buymeacoffee.com/admon" },
  { name: "PayPal", href: "https://paypal.me/aaronviehl" },
  { name: "Ko-fi", href: "https://ko-fi.com/admon" },
];

/** The note of the first start: how Mailrobbe came about, that its price is the user's choice,
 *  the ways to pay and the contact (D350). Shown once per browser. */
export function WelcomeDialog() {
  const [open, setOpen] = useState(() => !welcomeSeen());
  if (!open) return null;
  const close = () => {
    markWelcomeSeen();
    setOpen(false);
  };
  return (
    <Dialog title="Willkommen bei Mailrobbe" onClose={close}>
      <p className={styles.text}>
        Mailrobbe ist in drei bis vier Tagen entstanden. Viel KI-Arbeit steckt darin, aber auch viel
        Iteration, Nachdenken und Testen.
      </p>
      <p className={styles.text}>
        Die Software steht unter der AGPL-3.0 und ist frei nutzbar, auch für Redaktionen, Firmen und
        Behörden. Wenn sie dir Zeit spart, darfst du den Preis selbst wählen:
      </p>
      <div className={styles.links}>
        {SUPPORT_LINKS.map((link) => (
          <a
            key={link.name}
            className={buttonClass("outline")}
            href={link.href}
            target="_blank"
            rel="noopener noreferrer"
          >
            {link.name}
          </a>
        ))}
      </div>
      <p className={styles.contact}>
        Fragen, Lob, Kritik oder eine Rechnung: <a href="mailto:hey@admon.me">hey@admon.me</a>, auf
        Wunsch verschlüsselt mit{" "}
        <a
          href="https://github.com/admonstrator/Admonstrator/blob/main/pgp/hey@admon.me.asc"
          target="_blank"
          rel="noopener noreferrer"
        >
          diesem PGP-Schlüssel
        </a>
        .
      </p>
      <div className={styles.foot}>
        <Button variant="primary" onClick={close}>
          Verstanden
        </Button>
      </div>
    </Dialog>
  );
}
