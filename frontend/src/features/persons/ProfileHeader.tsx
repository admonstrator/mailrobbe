import { useState } from "react";
import { Link } from "react-router";

import { useUnmergePerson } from "../../api/queries";
import type { AliasAddress, PersonLabel, PersonProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { GraphIcon } from "../../components/icons";
import { formatDate, formatNumber } from "../../lib/format";
import { LabelDialog } from "./LabelDialog";
import { personErrorText, personLabel } from "./labels";
import styles from "./ProfileHeader.module.css";

// A longer note shows its start and "mehr".
const NOTE_PREVIEW = 240;

/** The profile's head (SPEC 5.3): who it is, the team's label of it (D156), its aliases and
 *  display names, map and export. */
export function ProfileHeader({
  profile,
  onMerge,
}: {
  profile: PersonProfile;
  onMerge: () => void;
}) {
  const [labelling, setLabelling] = useState(false);
  const exportQuery = new URLSearchParams({
    person: String(profile.id),
    hide_duplicates: "true",
  });
  const { label } = profile;
  // An alias's label shows until the person's own address is named.
  const own = label !== null && label.email === profile.email;
  return (
    <Card className={styles.card}>
      <Avatar
        personId={profile.id}
        name={label?.name || profile.name}
        email={profile.email}
        size="lg"
      />
      <div className={styles.identity}>
        <div className={styles.title}>
          <h1 className={styles.name}>{personLabel(profile)}</h1>
          {label?.role && <span className={styles.role}>{label.role}</span>}
        </div>
        <div className={styles.email}>
          {label?.name && profile.name && (
            <span className={styles.mailName}>{profile.name} · </span>
          )}
          {profile.email}
        </div>
        {label && <LabelNote label={label} own={own} />}
        <ul className={styles.chips} aria-label="Adressen">
          <li className={styles.chip}>Domain: {profile.domain}</li>
          {profile.aliases.map((alias) => (
            <AliasChip key={alias.person_id} alias={alias} />
          ))}
          <li>
            <button type="button" className={styles.add} onClick={onMerge}>
              + Adresse zusammenführen
            </button>
          </li>
        </ul>
        {profile.display_names.length > 0 && (
          <p className={styles.names}>
            Anzeigenamen in Mails:{" "}
            {profile.display_names
              .map(({ name, mails }) => `„${name}“ (${formatNumber(mails)})`)
              .join(", ")}
          </p>
        )}
      </div>
      <div className={styles.actions}>
        <Button onClick={() => setLabelling(true)}>
          {own ? "Benennung bearbeiten" : "Benennen"}
        </Button>
        <Link to={`/karte?center=${profile.id}`} className={buttonClass("primary")}>
          <GraphIcon size={14} />
          Im Graphen zeigen
        </Link>
        <a href={`/api/mails/export.csv?${exportQuery}`} className={buttonClass()} download>
          Alle Mails exportieren
        </a>
        <Link to={`/anhaenge?person=${profile.id}`} className={buttonClass()}>
          Anhänge dieser Person
        </Link>
      </div>
      {labelling && <LabelDialog profile={profile} onClose={() => setLabelling(false)} />}
    </Card>
  );
}

/** The label's note, shortened with "mehr" when long, and who named which address when. */
function LabelNote({ label, own }: { label: PersonLabel; own: boolean }) {
  const [open, setOpen] = useState(false);
  const note = label.note ?? "";
  const long = note.length > NOTE_PREVIEW;
  const by = [label.editor, formatDate(label.updated_at)].filter(Boolean).join(", ");
  return (
    <div className={styles.label}>
      {note && (
        <p className={styles.note}>
          {long && !open ? `${note.slice(0, NOTE_PREVIEW).trimEnd()} …` : note}
          {long && (
            <>
              {" "}
              <Button variant="link" size="xs" onClick={() => setOpen(!open)}>
                {open ? "weniger" : "mehr"}
              </Button>
            </>
          )}
        </p>
      )}
      <p className={styles.labelBy}>
        {`Benennung des Teams (${by})`}
        {own ? "" : `, von der Adresse ${label.email}`}
      </p>
    </div>
  );
}

/** An alias address with its "Lösen", which asks once inline before it unmerges. */
function AliasChip({ alias }: { alias: AliasAddress }) {
  const unmerge = useUnmergePerson();
  const [asking, setAsking] = useState(false);
  const mails = `${formatNumber(alias.mails)} ${alias.mails === 1 ? "Mail" : "Mails"}`;

  if (!asking) {
    return (
      <li className={styles.chip} title={mails}>
        Alias: {alias.email}
        {alias.label?.name && <span className={styles.aliasLabel}>„{alias.label.name}“</span>}
        <button
          type="button"
          className={styles.chipAction}
          aria-label={`Alias ${alias.email} lösen`}
          onClick={() => setAsking(true)}
        >
          Lösen
        </button>
      </li>
    );
  }
  return (
    <li className={styles.asking} title={mails}>
      <span>{alias.email} wieder als eigene Person führen?</span>
      <button
        type="button"
        className={styles.confirm}
        disabled={unmerge.isPending}
        onClick={() => unmerge.mutate(alias.person_id)}
      >
        Ja, lösen
      </button>
      <button
        type="button"
        className={styles.chipAction}
        disabled={unmerge.isPending}
        onClick={() => {
          unmerge.reset();
          setAsking(false);
        }}
      >
        Abbrechen
      </button>
      {unmerge.isError && (
        <span className={styles.error} role="alert">
          {personErrorText(unmerge.error)}
        </span>
      )}
    </li>
  );
}
