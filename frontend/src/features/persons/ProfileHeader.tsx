import { useState } from "react";
import { Link } from "react-router";

import { useUnmergePerson } from "../../api/queries";
import type { AliasAddress, PersonProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { GraphIcon } from "../../components/icons";
import { formatNumber } from "../../lib/format";
import { personErrorText, personLabel } from "./labels";
import styles from "./ProfileHeader.module.css";

/** The profile's head (SPEC 5.3): who it is, its aliases and display names, map and export. */
export function ProfileHeader({
  profile,
  onMerge,
}: {
  profile: PersonProfile;
  onMerge: () => void;
}) {
  const exportQuery = new URLSearchParams({
    person: String(profile.id),
    hide_duplicates: "true",
  });
  return (
    <Card className={styles.card}>
      <Avatar personId={profile.id} name={profile.name} email={profile.email} size="lg" />
      <div className={styles.identity}>
        <h1 className={styles.name}>{personLabel(profile)}</h1>
        <div className={styles.email}>{profile.email}</div>
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
    </Card>
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
