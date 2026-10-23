import { useState } from "react";
import { Link } from "react-router";

import { useUnmergePerson } from "../../api/queries";
import type { AliasAddress, PersonLabel, PersonProfile } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button } from "../../components/Button";
import { personPath } from "../../components/PersonLink";
import { formatDate, formatNumber, formatPercent } from "../../lib/format";
import { DEFAULT_LIST_STATE, listSearch, withFilters } from "../mails/listState";
import { ActiveIcon, AddressIcon, DomainIcon, NamesIcon, ShieldIcon } from "./factIcons";
import { LabelDialog } from "./LabelDialog";
import { personErrorText, personLabel } from "./labels";
import styles from "./ProfileAside.module.css";
import { ProfileMerges } from "./ProfileMerges";

// A longer note shows its start and "mehr".
const NOTE_PREVIEW = 240;
// Contacts the column shows as avatars.
const CONTACT_AVATARS = 10;

/** The domain's mails in the mail list. */
function domainHref(domain: string): string {
  return `/mails?${listSearch(withFilters(DEFAULT_LIST_STATE, { sender_domain: [domain] }))}`;
}

/** The profile's left column (D336): who it is, the team's label of it (D156), the facts, the
 *  most frequent contacts and the merges. */
export function ProfileAside({
  profile,
  onContacts,
  onMerge,
}: {
  profile: PersonProfile;
  /** Opens the tab of every contact. */
  onContacts: () => void;
  /** Opens the dialog that merges another address into the person. */
  onMerge: () => void;
}) {
  const [labelling, setLabelling] = useState(false);
  const [addresses, setAddresses] = useState(false);
  const { label, figures } = profile;
  // An alias's label shows until the person's own address is named.
  const own = label !== null && label.email === profile.email;
  const count = profile.aliases.length + 1;
  const contacts = profile.top_contacts.slice(0, CONTACT_AVATARS);
  const total = figures?.contacts ?? profile.top_contacts.length;
  const suggested = profile.suggestion_counts.certain + profile.suggestion_counts.uncertain;

  return (
    <aside className={styles.aside} aria-label="Steckbrief">
      <Avatar
        personId={profile.id}
        name={label?.name || profile.name}
        email={profile.email}
        size="xl"
      />
      <div className={styles.identity}>
        <h1 className={styles.name}>{personLabel(profile)}</h1>
        {label?.role && <span className={styles.role}>{label.role}</span>}
        <div className={styles.email}>
          {label?.name && profile.name && (
            <span className={styles.mailName}>{profile.name} · </span>
          )}
          {profile.email}
        </div>
      </div>
      {label && <LabelNote label={label} own={own} />}
      <Button className={styles.wide} onClick={() => setLabelling(true)}>
        {own ? "Benennung bearbeiten" : "Benennen"}
      </Button>

      <ul className={styles.facts} aria-label="Angaben">
        <li>
          <DomainIcon />
          <Link to={domainHref(profile.domain)} title="Mails von Adressen dieser Domain">
            {profile.domain}
          </Link>
        </li>
        <li>
          <AddressIcon />
          <div className={styles.fact}>
            <span>
              {count === 1 ? "1 Adresse" : `${formatNumber(count)} Adressen`}
              {count > 1 && (
                <>
                  {" "}
                  <button
                    type="button"
                    className={styles.toggle}
                    aria-expanded={addresses}
                    onClick={() => setAddresses(!addresses)}
                  >
                    {addresses ? "ausblenden" : "zeigen"}
                  </button>
                </>
              )}
            </span>
            {addresses && (
              <ul className={styles.addresses} aria-label="Adressen">
                <li className={styles.address}>{profile.email}</li>
                {profile.aliases.map((alias) => (
                  <AliasRow key={alias.person_id} alias={alias} />
                ))}
              </ul>
            )}
            {suggested > 0 && (
              <button type="button" className={styles.toggle} onClick={onMerge}>
                {suggested === 1
                  ? "1 Vorschlag zum Zusammenführen"
                  : `${formatNumber(suggested)} Vorschläge zum Zusammenführen`}
              </button>
            )}
          </div>
        </li>
        {profile.display_names.length > 0 && (
          <li>
            <NamesIcon />
            <span className={styles.fact}>
              {"Heißt in Mails "}
              {profile.display_names
                .map(({ name, mails }) => `„${name}“ (${formatNumber(mails)})`)
                .join(", ")}
            </span>
          </li>
        )}
        {figures?.first_date && figures.last_date && (
          <li>
            <ActiveIcon />
            <span className={styles.fact}>
              {`Aktiv ${formatDate(figures.first_date)} bis ${formatDate(figures.last_date)}`}
            </span>
          </li>
        )}
        {figures && (
          <li>
            <ShieldIcon />
            <span className={styles.fact}>
              {figures.dkim_pass_ratio === null
                ? "Keine geprüfte Mail gesendet"
                : `DKIM gültig bei ${formatPercent(figures.dkim_pass_ratio)} der gesendeten Mails`}
            </span>
          </li>
        )}
      </ul>

      {contacts.length > 0 && (
        <section className={styles.block} aria-labelledby="profile-contacts-title">
          <div className={styles.blockHead}>
            <h2 id="profile-contacts-title" className={styles.blockTitle}>
              Häufigste Kontakte
            </h2>
            <Button variant="link" size="sm" onClick={onContacts}>
              {`Alle ${formatNumber(total)}`}
            </Button>
          </div>
          <ul className={styles.avatars}>
            {contacts.map((contact) => {
              const name = personLabel(contact.person);
              return (
                <li key={contact.person.person_id}>
                  <Link
                    to={personPath(contact.person.person_id)}
                    className={styles.avatarLink}
                    title={`${name}, ${formatNumber(contact.mails)} Mails`}
                    aria-label={name}
                  >
                    <Avatar
                      personId={contact.person.person_id}
                      name={contact.person.label?.name || contact.person.name}
                      email={contact.person.email}
                    />
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <ProfileMerges merges={profile.merges} />
      {labelling && <LabelDialog profile={profile} onClose={() => setLabelling(false)} />}
    </aside>
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
function AliasRow({ alias }: { alias: AliasAddress }) {
  const unmerge = useUnmergePerson();
  const [asking, setAsking] = useState(false);
  const mails = `${formatNumber(alias.mails)} ${alias.mails === 1 ? "Mail" : "Mails"}`;

  if (!asking) {
    return (
      <li className={styles.address} title={mails}>
        <span>
          {alias.email}
          {alias.label?.name && <span className={styles.aliasLabel}> „{alias.label.name}“</span>}
        </span>
        <button
          type="button"
          className={styles.action}
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
      <span className={styles.answers}>
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
          className={styles.action}
          disabled={unmerge.isPending}
          onClick={() => {
            unmerge.reset();
            setAsking(false);
          }}
        >
          Abbrechen
        </button>
      </span>
      {unmerge.isError && (
        <span className={styles.error} role="alert">
          {personErrorText(unmerge.error)}
        </span>
      )}
    </li>
  );
}
