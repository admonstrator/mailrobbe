import { useState } from "react";

import { ApiError } from "../../api/client";
import { useSaveSettings, useSettings } from "../../api/queries";
import type { SettingInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { FoldCard } from "../../components/FoldCard";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime } from "../../lib/format";
import { GROUPS, SOURCE_LABELS, type SettingGroup, type SettingText } from "./labels";
import { changes, fieldValue, formatSetting, type Draft } from "./model";
import styles from "./SettingsPage.module.css";

const OPEN_GROUPS = new Set(["archive", "ai-text", "ai-vision"]);

/** The page "Einstellungen" (D313): every setting the server lets the page change, in groups,
 *  with where its value comes from. Changes collect in a draft until "Speichern". */
export function SettingsPage() {
  const settings = useSettings();
  return (
    <main className={styles.page}>
      <title>Einstellungen · Mailrobbe</title>
      <h1 className={styles.title}>Einstellungen</h1>
      <p className={styles.intro}>
        Diese Werte gehen den gleichnamigen Einträgen der .env vor. „Zurücksetzen“ holt den Wert aus
        der .env oder den Standard zurück. Eine Änderung gilt sofort für die Oberfläche und für
        jeden Lauf, der danach startet; ein laufender Import oder KI-Lauf behält seine Werte. Nur in
        der .env stehen die Datenbank, die Pfade, Host und Port, der Zugangsschutz (Basic Auth) und
        die Freigabe für KI-Dienste außerhalb dieses Rechners.
      </p>
      {settings.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Einstellungen werden geladen" />
        </Card>
      ) : settings.isError ? (
        <Card>
          <ErrorState
            title="Die Einstellungen konnten nicht geladen werden."
            actions={<Button onClick={() => void settings.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <Form items={settings.data.items} />
      )}
    </main>
  );
}

function Form({ items }: { items: SettingInfo[] }) {
  const save = useSaveSettings();
  const [draft, setDraft] = useState<Draft>({});
  const [saved, setSaved] = useState(false);
  const { values, invalid } = changes(items, draft);
  const count = Object.keys(values).length;
  const rejected = rejectedSetting(save.error);
  const texts = textsByName();

  function edit(name: string, value: string | boolean | null) {
    setDraft((current) => ({ ...current, [name]: value }));
    setSaved(false);
    save.reset();
  }

  function onSave() {
    save.mutate(
      { values },
      {
        onSuccess: () => {
          setDraft({});
          setSaved(true);
        },
      },
    );
  }

  return (
    <>
      {groupsOf(items).map(({ group, members }) => {
        const stored = members.filter((item) => item.source === "stored").length;
        return (
          <FoldCard
            key={group.id}
            id={`settings-${group.id}`}
            variant="main"
            title={group.title}
            summary={stored > 0 ? `${stored} geändert` : undefined}
            defaultOpen={OPEN_GROUPS.has(group.id)}
          >
            {group.note && <p className={styles.note}>{group.note}</p>}
            <div className={styles.rows}>
              {members.map((item) => (
                <Field
                  key={item.name}
                  item={item}
                  text={texts.get(item.name) ?? { label: item.name }}
                  value={fieldValue(item, draft)}
                  resetting={draft[item.name] === null}
                  invalid={invalid.includes(item.name)}
                  rejected={rejected?.name === item.name ? rejected.reason : null}
                  onChange={(value) => edit(item.name, value)}
                />
              ))}
            </div>
          </FoldCard>
        );
      })}
      {(count > 0 || invalid.length > 0 || save.isError || saved) && (
        <div className={styles.bar} role="region" aria-label="Änderungen">
          <p className={styles.barText} role="status">
            {save.isError
              ? rejected
                ? `Nicht gespeichert: „${texts.get(rejected.name)?.label ?? rejected.name}“ nimmt diesen Wert nicht an.`
                : "Nicht gespeichert: Der Server hat einen Fehler gemeldet."
              : invalid.length > 0
                ? `Keine Zahl: ${invalid.map((name) => `„${texts.get(name)?.label ?? name}“`).join(", ")}`
                : count > 0
                  ? `${count} ${count === 1 ? "Änderung" : "Änderungen"}`
                  : "Gespeichert."}
          </p>
          {(count > 0 || invalid.length > 0) && (
            <>
              <Button onClick={() => setDraft({})} disabled={save.isPending}>
                Verwerfen
              </Button>
              <Button
                variant="primary"
                onClick={onSave}
                disabled={count === 0 || invalid.length > 0 || save.isPending}
              >
                {save.isPending ? "Wird gespeichert …" : "Speichern"}
              </Button>
            </>
          )}
        </div>
      )}
    </>
  );
}

function Field({
  item,
  text,
  value,
  resetting,
  invalid,
  rejected,
  onChange,
}: {
  item: SettingInfo;
  text: SettingText;
  value: string | boolean;
  resetting: boolean;
  invalid: boolean;
  rejected: string | null;
  onChange: (value: string | boolean | null) => void;
}) {
  const id = `setting-${item.name}`;
  const helpId = `${id}-help`;
  return (
    <div className={cx(styles.row, (invalid || rejected) && styles.error)}>
      <div className={styles.labelColumn}>
        <label htmlFor={id} className={styles.label}>
          {text.label}
        </label>
        {text.help && (
          <p id={helpId} className={styles.help}>
            {text.help}
          </p>
        )}
      </div>
      <div className={styles.controlColumn}>
        <div className={styles.control}>
          <Control
            id={id}
            item={item}
            text={text}
            value={value}
            describedBy={text.help ? helpId : undefined}
            onChange={onChange}
          />
          {text.unit && item.kind !== "boolean" && <span className={styles.unit}>{text.unit}</span>}
        </div>
        <p className={styles.source}>
          {rejected
            ? `Nicht angenommen: ${rejected}`
            : resetting
              ? "Wird beim Speichern zurückgesetzt."
              : item.source === "stored"
                ? `Hier geändert${item.changed_by ? ` von ${item.changed_by}` : ""}${item.changed_at ? ` am ${formatDateTime(item.changed_at)}` : ""}; sonst ${formatSetting(item, item.base, text.choices)}.`
                : SOURCE_LABELS[item.source]}
          {item.source === "stored" && !resetting && (
            <Button variant="link" size="xs" onClick={() => onChange(null)}>
              Zurücksetzen
            </Button>
          )}
        </p>
      </div>
    </div>
  );
}

function Control({
  id,
  item,
  text,
  value,
  describedBy,
  onChange,
}: {
  id: string;
  item: SettingInfo;
  text: SettingText;
  value: string | boolean;
  describedBy?: string;
  onChange: (value: string | boolean) => void;
}) {
  const common = { id, "aria-describedby": describedBy };
  if (item.kind === "boolean") {
    return (
      <input
        {...common}
        type="checkbox"
        className={styles.check}
        checked={value === true}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }
  if (item.kind === "choice") {
    return (
      <select
        {...common}
        className={styles.select}
        value={String(value)}
        onChange={(event) => onChange(event.target.value)}
      >
        {item.choices.map((choice) => (
          <option key={choice} value={choice}>
            {text.choices?.[choice] ?? choice}
          </option>
        ))}
      </select>
    );
  }
  const numeric = item.kind === "integer" || item.kind === "number" || item.kind === "bytes";
  return (
    <input
      {...common}
      type={item.kind === "secret" ? "password" : numeric ? "number" : "text"}
      className={numeric ? styles.number : styles.text}
      value={String(value)}
      min={item.minimum ?? (item.kind === "bytes" ? 0 : undefined)}
      max={item.maximum ?? undefined}
      step={item.kind === "integer" ? 1 : "any"}
      placeholder={
        item.kind === "secret"
          ? item.secret_set
            ? "gesetzt, leer lassen zum Behalten"
            : "keiner"
          : undefined
      }
      autoComplete={item.kind === "secret" ? "new-password" : "off"}
      spellCheck={false}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

/** The groups of labels.ts with the settings the server sent, then "Weitere" for the rest. */
function groupsOf(items: SettingInfo[]): { group: SettingGroup; members: SettingInfo[] }[] {
  const byName = new Map(items.map((item) => [item.name, item]));
  const listed = new Set<string>();
  const groups = GROUPS.map((group) => {
    const members = Object.keys(group.settings).flatMap((name) => {
      const item = byName.get(name);
      if (item) listed.add(name);
      return item ? [item] : [];
    });
    return { group, members };
  });
  const rest = items.filter((item) => !listed.has(item.name));
  groups.push({ group: { id: "more", title: "Weitere", settings: {} }, members: rest });
  return groups.filter(({ members }) => members.length > 0);
}

function textsByName(): Map<string, SettingText> {
  return new Map(GROUPS.flatMap((group) => Object.entries(group.settings)));
}

/** The setting a save was refused for (invalid_setting: "<name>: <reason>"), or null. */
function rejectedSetting(error: Error | null): { name: string; reason: string } | null {
  if (!(error instanceof ApiError) || error.code !== "invalid_setting") return null;
  const colon = error.message.indexOf(": ");
  if (colon < 0) return null;
  return { name: error.message.slice(0, colon), reason: error.message.slice(colon + 2) };
}
