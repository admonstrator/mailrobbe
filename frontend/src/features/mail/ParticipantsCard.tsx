import { Link } from "react-router";

import type { Participant, ParticipationRole } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { GraphIcon } from "../../components/icons";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import styles from "./ParticipantsCard.module.css";

const ROLE_LABELS: Record<ParticipationRole, string> = {
  from: "Absender",
  to: "An",
  cc: "Cc",
  bcc: "Bcc",
};

/** "3.412 Mails · 214 Kontakte" for the sender, "1.980 Mails · 388 mit Anna Keller" for the
 *  others; only the figures milestone 5 has filled (D26). */
function figures(person: Participant, senderName: string | null): string | null {
  const parts: string[] = [];
  if (person.mails !== null) parts.push(`${formatNumber(person.mails)} Mails`);
  if (person.role === "from") {
    if (person.contacts !== null) parts.push(`${formatNumber(person.contacts)} Kontakte`);
  } else if (person.mails_with_sender !== null && senderName) {
    parts.push(`${formatNumber(person.mails_with_sender)} mit ${senderName}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

export function ParticipantsCard({ participants }: { participants: Participant[] }) {
  const sender = participants.find((person) => person.role === "from");
  const senderName = sender ? personName(sender) : null;
  const ids = [...new Set(participants.map((person) => person.person_id))];

  return (
    <Card variant="side" className={styles.card}>
      <CardTitle variant="caps">Beteiligte</CardTitle>
      <ul className={styles.list}>
        {participants.map((person) => {
          const line = figures(person, senderName);
          return (
            <li key={`${person.role}-${person.person_id}`}>
              <Link
                to={personPath(person.person_id)}
                className={styles.person}
                title={person.email}
              >
                <Avatar
                  personId={person.person_id}
                  name={person.label?.name || person.name}
                  email={person.email}
                />
                <span className={styles.text}>
                  <span className={styles.name}>
                    {personName(person)}{" "}
                    {person.label?.role && (
                      <span className={styles.role}>· {person.label.role} </span>
                    )}
                    <span className={styles.role}>· {ROLE_LABELS[person.role]}</span>
                  </span>
                  {line && <span className={styles.figures}>{line}</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {ids.length > 0 && (
        <Link
          to={`/karte?center=${ids.join(",")}`}
          className={`${buttonClass("outline", "sm")} ${styles.graph}`}
        >
          <GraphIcon size={14} />
          {ids.length === 1
            ? "Im Graphen zeigen"
            : `Diese ${formatNumber(ids.length)} im Graphen zeigen`}
        </Link>
      )}
    </Card>
  );
}
