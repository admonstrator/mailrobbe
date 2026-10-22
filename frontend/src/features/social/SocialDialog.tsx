import { useMemo, useState } from "react";

import { socialImageUrl } from "../../api/client";
import { useSocialCard } from "../../api/queries";
import {
  SOCIAL_TERM_LIMIT,
  SOCIAL_TERMS_LIMIT,
  type RedactionKind,
  type SocialParams,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { Dialog } from "../persons/Dialog";
import styles from "./SocialDialog.module.css";

const SHAPES = [
  { value: "portrait", label: "Hochformat", size: "1080 × 1350" },
  { value: "square", label: "Quadrat", size: "1080 × 1080" },
  { value: "wide", label: "Breitbild", size: "1200 × 675" },
] as const;

const SWITCHES = [
  { key: "participants", label: "Beteiligte (Von, An, Cc)" },
  { key: "contacts", label: "Adressen, Telefonnummern, IBANs im Text" },
  { key: "names", label: "Personennamen im Text" },
  { key: "organizations", label: "Organisationen, Orte und Links im Text" },
] as const;

const KINDS: Record<RedactionKind, string> = {
  participant: "Beteiligte",
  contact: "Kontaktdaten",
  name: "Namen im Text",
  organization: "Organisationen und Orte",
  term: "Eigene Begriffe",
};

const DELAY = 400; // ms a changed option waits before a new picture is asked for

/** The mail as a picture for soziale Medien (D217): the preview beside the switches of the
 *  redaction, what it blacked out, and the download. The picture is drawn for each preview and
 *  stored nowhere; what it can show is what the card says (D216). */
export function SocialDialog({ mailId, onClose }: { mailId: number; onClose: () => void }) {
  const [options, setOptions] = useState<SocialParams>({ shape: "portrait" });
  const [typed, setTyped] = useState("");

  const asked = useMemo<SocialParams>(() => {
    const terms = typed
      .split(",")
      .map((term) => term.trim().slice(0, SOCIAL_TERM_LIMIT))
      .filter(Boolean)
      .slice(0, SOCIAL_TERMS_LIMIT);
    return terms.length ? { ...options, terms } : options;
  }, [options, typed]);
  const shown = useDebounced(asked, DELAY);
  const card = useSocialCard(mailId, shown).data;
  const image = socialImageUrl(mailId, shown);

  function set(change: Partial<SocialParams>) {
    setOptions((before) => ({ ...before, ...change }));
  }

  return (
    <Dialog title="Als Bild für Soziale Medien" onClose={onClose} wide>
      <div className={styles.columns}>
        <figure className={styles.preview}>
          <img className={styles.image} src={image} alt="Vorschau des Bildes" />
        </figure>
        <div className={styles.options}>
          <fieldset className={styles.group}>
            <legend className={styles.legend}>Format</legend>
            {SHAPES.map((shape) => (
              <label key={shape.value} className={styles.radio}>
                <input
                  type="radio"
                  name="shape"
                  checked={(options.shape ?? "portrait") === shape.value}
                  onChange={() => set({ shape: shape.value })}
                />
                <span>{shape.label}</span>
                <span className={styles.size}>{shape.size}</span>
              </label>
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend className={styles.legend}>Schwärzen</legend>
            {SWITCHES.map((item) => (
              <Checkbox
                key={item.key}
                checked={options[item.key] ?? item.key !== "organizations"}
                onChange={(checked) => set({ [item.key]: checked })}
              >
                {item.label}
              </Checkbox>
            ))}
            <label className={styles.field}>
              <span>Eigene Begriffe, mit Komma getrennt</span>
              <input
                className={styles.input}
                value={typed}
                placeholder="Projekt Nord, Aktenzeichen 12/34"
                onChange={(event) => setTyped(event.target.value)}
              />
            </label>
          </fieldset>

          <fieldset className={styles.group}>
            <legend className={styles.legend}>Zeigen</legend>
            <Checkbox
              checked={options.quotes ?? false}
              onChange={(checked) => set({ quotes: checked })}
            >
              Zitierten Text mitzeigen
            </Checkbox>
            <Checkbox checked={options.dkim ?? true} onChange={(checked) => set({ dkim: checked })}>
              DKIM-Siegel
            </Checkbox>
            <Checkbox
              checked={options.checksum ?? true}
              onChange={(checked) => set({ checksum: checked })}
            >
              Prüfsumme der Mail
            </Checkbox>
          </fieldset>

          <p className={styles.figures}>
            {card
              ? card.places
                ? `${formatNumber(card.places)} Stellen geschwärzt: ` +
                  card.redactions
                    .map((part) => `${KINDS[part.kind]} ${formatNumber(part.places)}`)
                    .join(", ")
                : "Nichts geschwärzt"
              : "Bild wird erstellt …"}
            {card?.truncated && " · Der Text passt nicht ganz ins Format und ist gekürzt."}
          </p>
          <p className={styles.hint}>
            Mailrobbe schwärzt, was es erkennt. Sieh dir das Bild vor dem Veröffentlichen an und
            ergänze fehlende Stellen als eigene Begriffe.
          </p>
        </div>
      </div>
      <div className={styles.foot}>
        <Button onClick={onClose}>Schließen</Button>
        <a
          href={image}
          download={`mailrobbe-${mailId}-social.png`}
          className={buttonClass("primary")}
        >
          PNG herunterladen
        </a>
      </div>
    </Dialog>
  );
}
