import { Fragment, useState } from "react";
import { Link } from "react-router";

import type { MailDetail } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { describeRule, joinGerman, keptReasons, subjectStart } from "./labels";
import styles from "./MailHiding.module.css";
import { RuleDialog, type RuleDraft } from "./RuleDialog";

/** The note of a hidden mail (D222): the rules matching it, with the way to them, and whether
 *  the team keeps it visible all the same (D203), and why; read from the mail's research data,
 *  so a new note or Akte shows at once. */
export function HiddenNote({ mail }: { mail: MailDetail }) {
  const rules = mail.hidden?.rules ?? [];
  if (rules.length === 0) return null;
  const reasons = keptReasons(mail.research);
  return (
    <Card className={styles.note} aria-label="Ausgeblendet">
      <p className={styles.text}>
        Ausgeblendet durch {rules.length === 1 ? "die Regel" : "die Regeln"}{" "}
        {rules.map((rule, index) => (
          <Fragment key={rule.id}>
            {index > 0 && (index === rules.length - 1 ? " und " : ", ")}
            <Link to="/ausgeblendet">„{rule.name || describeRule(rule)}“</Link>
          </Fragment>
        ))}
        .{" "}
        {reasons.length > 0
          ? `Sie bleibt trotzdem in Liste und Suche, weil sie ${joinGerman(reasons)}.`
          : "Sie fehlt deshalb in Liste und Suche; das Suchmenü bezieht ausgeblendete Mails auf Wunsch ein."}
      </p>
    </Card>
  );
}

/** "Mails wie diese ausblenden" (D223): the rule dialog filled with the mail's sender, its
 *  List-Id and the start of its subject; the user keeps the criteria that fit. */
export function HideCard({ mail }: { mail: MailDetail }) {
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  return (
    <Card variant="side">
      <CardTitle variant="caps">Ausblenden</CardTitle>
      <Button variant="outline" size="sm" onClick={() => setDraft(mailDraft(mail))}>
        Mails wie diese ausblenden
      </Button>
      {draft && <RuleDialog draft={draft} onClose={() => setDraft(null)} />}
    </Card>
  );
}

/** The criteria a mail suggests: its sender's address (its person offered beside it), its
 *  List-Id, and the start of its subject without Re:, AW:, Fwd: or WG:. */
export function mailDraft(mail: MailDetail): RuleDraft {
  const sender = mail.participants.find((person) => person.role === "from");
  const subject = subjectStart(mail.subject);
  return {
    sender: sender?.email ?? null,
    person: sender
      ? { person_id: sender.person_id, email: sender.email, name: sender.name, label: sender.label }
      : null,
    list_id: mail.list_id ?? null,
    subject: subject || null,
    subject_match: "starts",
  };
}
