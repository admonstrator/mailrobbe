import { useMemo, useState } from "react";

import { socialImageUrl, type SocialTarget } from "../../api/client";
import { useSocialCard } from "../../api/queries";
import {
  SOCIAL_TERM_LIMIT,
  SOCIAL_TERMS_LIMIT,
  type RedactionKind,
  type TranscriptSocialParams,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { formatClock, formatNumber, parseClock } from "../../lib/format";
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

/** The part of a recording typed into the dialog: start and end in seconds, either left out,
 *  or why it cannot be used. */
function excerptOf(from: string, to: string): { start?: number; end?: number; problem?: string } {
  const start = from.trim() ? parseClock(from) : undefined;
  const end = to.trim() ? parseClock(to) : undefined;
  if (start === null || end === null) return { problem: "Zeiten als m:ss angeben, etwa 0:13." };
  if (start !== undefined && end !== undefined && start >= end) {
    return { problem: "Der Anfang muss vor dem Ende liegen." };
  }
  return { start, end: end === 0 ? undefined : end };
}

/** A mail, or a transcribed recording with the mail it came with (D298), as a picture for
 *  soziale Medien (D217): the preview beside the switches of the redaction, what it blacked out,
 *  and the download; for a recording also the part of it to show. The picture is drawn for each
 *  preview and stored nowhere; what it can show is what the card says (D216). */
export function SocialDialog({
  target,
  duration = null,
  onClose,
}: {
  target: SocialTarget;
  /** The recording's length in seconds, as the hint of its excerpt. */
  duration?: number | null;
  onClose: () => void;
}) {
  const transcript = "document" in target;
  const [options, setOptions] = useState<TranscriptSocialParams>({ shape: "portrait" });
  const [typed, setTyped] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const excerpt = useMemo(() => excerptOf(from, to), [from, to]);

  const asked = useMemo<TranscriptSocialParams>(() => {
    const terms = typed
      .split(",")
      .map((term) => term.trim().slice(0, SOCIAL_TERM_LIMIT))
      .filter(Boolean)
      .slice(0, SOCIAL_TERMS_LIMIT);
    const { start, end } = excerpt;
    return {
      ...options,
      ...(terms.length ? { terms } : {}),
      ...(transcript && start !== undefined ? { start } : {}),
      ...(transcript && end !== undefined ? { end } : {}),
    };
  }, [options, typed, excerpt, transcript]);
  const shown = useDebounced(asked, DELAY);
  const card = useSocialCard(target, shown).data;
  const image = socialImageUrl(target, shown);
  const file =
    "mail" in target
      ? `mailrobbe-${target.mail}-social.png`
      : `mailrobbe-dokument-${target.document}-social.png`;

  function set(change: Partial<TranscriptSocialParams>) {
    setOptions((before) => ({ ...before, ...change }));
  }

  return (
    <Dialog
      title={transcript ? "Transkript als Bild für Soziale Medien" : "Als Bild für Soziale Medien"}
      onClose={onClose}
      wide
    >
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

          {transcript && (
            <fieldset className={styles.group}>
              <legend className={styles.legend}>Ausschnitt</legend>
              <div className={styles.range}>
                <label className={styles.field}>
                  <span>von</span>
                  <input
                    className={styles.input}
                    value={from}
                    placeholder="0:00"
                    inputMode="numeric"
                    onChange={(event) => setFrom(event.target.value)}
                  />
                </label>
                <label className={styles.field}>
                  <span>bis</span>
                  <input
                    className={styles.input}
                    value={to}
                    placeholder={duration ? formatClock(duration) : "Ende"}
                    inputMode="numeric"
                    onChange={(event) => setTo(event.target.value)}
                  />
                </label>
              </div>
              <p className={styles.hint} role={excerpt.problem ? "alert" : undefined}>
                {excerpt.problem ??
                  "Leer lassen für die ganze Aufnahme; gezeigt werden die Zeilen, die in die Zeit fallen."}
              </p>
            </fieldset>
          )}

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
            {!transcript && (
              <Checkbox
                checked={options.quotes ?? false}
                onChange={(checked) => set({ quotes: checked })}
              >
                Zitierten Text mitzeigen
              </Checkbox>
            )}
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
            {card?.truncated &&
              (transcript
                ? " · Das Transkript passt nicht ganz ins Format und ist gekürzt."
                : " · Der Text passt nicht ganz ins Format und ist gekürzt.")}
          </p>
          <p className={styles.hint}>
            Mailrobbe schwärzt, was es erkennt. Sieh dir das Bild vor dem Veröffentlichen an und
            ergänze fehlende Stellen als eigene Begriffe.
          </p>
        </div>
      </div>
      <div className={styles.foot}>
        <Button onClick={onClose}>Schließen</Button>
        <a href={image} download={file} className={buttonClass("primary")}>
          PNG herunterladen
        </a>
      </div>
    </Dialog>
  );
}
