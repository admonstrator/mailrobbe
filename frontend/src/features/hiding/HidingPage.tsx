import { useState } from "react";
import { Link } from "react-router";

import {
  useDeleteHideRule,
  useHideRules,
  useHideSuggestions,
  useUpdateHideRule,
} from "../../api/queries";
import type { HideRuleFields, HideRuleInfo, HideSuggestion } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDate, formatDateTime, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { ConfirmDialog } from "../research/ConfirmDialog";
import { mailCount } from "../research/labels";
import { HiddenTabs } from "./HiddenTabs";
import styles from "./HidingPage.module.css";
import { describeRule, hidingErrorText } from "./labels";
import { RuleDialog, type RuleDraft } from "./RuleDialog";

/** The list with the hidden mails included (D222). */
const WITH_HIDDEN = "/mails?include_hidden=true";

/** "Ausgeblendet · Ausblendregeln" (D223): the team's rules with their mails, who made and
 *  changed them, switch, edit and delete; the totals; and the suggestions, mailing lists and
 *  automated senders with many mails, each a click away from a rule. */
export function HidingPage() {
  const rules = useHideRules();
  const toggle = useUpdateHideRule();
  const remove = useDeleteHideRule();
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [deleting, setDeleting] = useState<HideRuleInfo | null>(null);
  const switching = toggle.isPending ? toggle.variables.id : null;

  function onToggle(rule: HideRuleInfo) {
    toggle.mutate({ id: rule.id, ...criteriaOf(rule), enabled: !rule.enabled });
  }

  return (
    <main className={styles.page}>
      <title>Ausblendregeln · Mailrobbe</title>
      <HiddenTabs />
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Ausblendregeln nehmen Newsletter, Rundmails und Systemmails aus Mailliste, Suche,
          Zeitachse und Export. Sie gelten für das ganze Team; Mails in einer Akte, mit Notiz,
          Lesezeichen oder „relevant“ bleiben immer sichtbar, und das Suchmenü bezieht die
          ausgeblendeten auf Wunsch ein.
        </p>
        <Button variant="primary" onClick={() => setDraft({})}>
          Neue Regel
        </Button>
      </div>
      <div className={styles.columns}>
        <div className={styles.main}>
          {rules.isPending ? (
            <Card className={styles.loading}>
              <Spinner label="Ausblendregeln werden geladen" />
            </Card>
          ) : rules.isError ? (
            <Card>
              <ErrorState
                title="Die Ausblendregeln konnten nicht geladen werden."
                actions={<Button onClick={() => void rules.refetch()}>Erneut versuchen</Button>}
              >
                Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
              </ErrorState>
            </Card>
          ) : rules.data.rules.length === 0 ? (
            <Card>
              <EmptyState
                title="Noch keine Ausblendregel"
                actions={
                  <Button variant="primary" onClick={() => setDraft({})}>
                    Erste Regel anlegen
                  </Button>
                }
              >
                Eine Regel blendet Mails aus, die bei der Recherche nur stören: Newsletter,
                Verteiler, Benachrichtigungen. Sie fehlen dann in Liste, Suche und Zahlen, bleiben
                aber im Archiv und lassen sich jederzeit einbeziehen. Rechts stehen Vorschläge; in
                einer Mail entsteht eine Regel mit „Mails wie diese ausblenden“.
              </EmptyState>
            </Card>
          ) : (
            <>
              <p className={styles.totals}>
                <strong>{formatNumber(rules.data.hidden)}</strong>{" "}
                {rules.data.hidden === 1 ? "Mail ist" : "Mails sind"} ausgeblendet
                {rules.data.kept > 0 &&
                  `, ${formatNumber(rules.data.kept)} weitere ${rules.data.kept === 1 ? "passt" : "passen"}, ${rules.data.kept === 1 ? "bleibt" : "bleiben"} aber sichtbar (Akte, Notiz, Lesezeichen oder „relevant“)`}
                . <Link to={WITH_HIDDEN}>Liste mit ausgeblendeten Mails</Link>
              </p>
              {toggle.isError && (
                <p className={styles.error} role="alert">
                  {hidingErrorText(toggle.error)}
                </p>
              )}
              <Card className={styles.listCard}>
                <ul className={styles.list} aria-label="Ausblendregeln">
                  {rules.data.rules.map((rule) => (
                    <RuleItem
                      key={rule.id}
                      rule={rule}
                      switching={switching === rule.id}
                      onToggle={() => onToggle(rule)}
                      onEdit={() => setDraft(rule)}
                      onDelete={() => {
                        remove.reset();
                        setDeleting(rule);
                      }}
                    />
                  ))}
                </ul>
              </Card>
            </>
          )}
        </div>
        <Suggestions onPick={setDraft} />
      </div>
      {draft && <RuleDialog draft={draft} onRulesPage onClose={() => setDraft(null)} />}
      {deleting && (
        <ConfirmDialog
          title="Ausblendregel löschen"
          confirmLabel="Löschen"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          Die Regel „{ruleTitle(deleting)}“ wird gelöscht.{" "}
          {deleting.enabled && deleting.mails > 0
            ? `Ihre ${mailCount(deleting.mails)} erscheinen sofort wieder in Liste und Suche, sofern keine andere Regel sie ausblendet.`
            : "Sie blendet gerade keine Mail aus."}{" "}
          Wer die Angaben behalten will, schaltet sie stattdessen aus.
        </ConfirmDialog>
      )}
    </main>
  );
}

function RuleItem({
  rule,
  switching,
  onToggle,
  onEdit,
  onDelete,
}: {
  rule: HideRuleInfo;
  switching: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const title = ruleTitle(rule);
  return (
    <li className={cx(styles.item, !rule.enabled && styles.off)}>
      <div className={styles.itemMain}>
        <span className={styles.itemTitle}>{title}</span>
        {rule.name && <span className={styles.criteria}>{describeRule(rule)}</span>}
        <span className={styles.meta}>{madeBy(rule)}</span>
      </div>
      <div className={styles.itemActions}>
        <span
          className={styles.count}
          title={rule.computed_at ? `Gezählt am ${formatDateTime(rule.computed_at)}` : undefined}
        >
          {rule.enabled ? mailCount(rule.mails) : "ausgeschaltet"}
        </span>
        <label className={styles.switch}>
          <input
            type="checkbox"
            role="switch"
            checked={rule.enabled}
            disabled={switching}
            aria-label={`„${title}“ aktiv`}
            onChange={onToggle}
          />
          aktiv
        </label>
        <Button size="sm" onClick={onEdit} aria-label={`„${title}“ bearbeiten`}>
          Bearbeiten
        </Button>
        <Button size="sm" onClick={onDelete} aria-label={`„${title}“ löschen`}>
          Löschen
        </Button>
      </div>
    </li>
  );
}

/** The suggestions (D223): each opens the dialog filled with its list or sender. */
function Suggestions({ onPick }: { onPick: (draft: RuleDraft) => void }) {
  const suggestions = useHideSuggestions();
  return (
    <aside className={styles.side} aria-labelledby="hide-suggestions">
      <Card variant="side">
        <CardTitle variant="caps" id="hide-suggestions">
          Vorschläge
        </CardTitle>
        <p className={styles.sideText}>
          Verteiler und automatische Absender mit den meisten Mails, die noch keine Regel
          ausblendet. Gezählt werden nur diese Mails.
        </p>
        {suggestions.isPending ? (
          <Spinner label="Vorschläge werden geladen" />
        ) : suggestions.isError ? (
          <p className={styles.sideText}>Die Vorschläge sind gerade nicht verfügbar.</p>
        ) : suggestions.data.length === 0 ? (
          <p className={styles.sideText}>
            Keine Vorschläge: Für die Verteiler und automatischen Absender gibt es schon Regeln.
          </p>
        ) : (
          <ul className={styles.suggestions}>
            {suggestions.data.map((suggestion) => {
              const name = suggestionName(suggestion);
              return (
                <li key={`${suggestion.kind}-${name}`} className={styles.suggestion}>
                  <div className={styles.suggestionMain}>
                    <span className={styles.suggestionName}>{name}</span>
                    <span className={styles.meta}>
                      {suggestion.kind === "list"
                        ? "Verteiler"
                        : `Absender ${suggestion.person?.email ?? ""}`}{" "}
                      · {mailCount(suggestion.mails)}
                    </span>
                  </div>
                  <Button
                    size="xs"
                    onClick={() => onPick(suggestionDraft(suggestion))}
                    aria-label={`Regel für ${name} anlegen`}
                  >
                    Regel anlegen
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
        <Link to={WITH_HIDDEN} className={buttonClass("link", "sm")}>
          Ausgeblendete Mails ansehen
        </Link>
      </Card>
    </aside>
  );
}

function ruleTitle(rule: HideRuleInfo): string {
  return rule.name || describeRule(rule);
}

/** The criteria of a rule, for a write that sends every field anew. */
function criteriaOf(rule: HideRuleInfo): HideRuleFields {
  const { name, sender, person_id, domain, list_id, automated, subject, subject_match } = rule;
  return { name, sender, person_id, domain, list_id, automated, subject, subject_match };
}

/** "angelegt von Anna am 22.10.2026 · geändert von Bert am 23.10.2026" */
function madeBy(rule: HideRuleInfo): string {
  const made = `angelegt ${by(rule.created_by)}am ${formatDate(rule.created_at)}`;
  if (rule.updated_at === rule.created_at) return made;
  return `${made} · geändert ${by(rule.updated_by)}am ${formatDate(rule.updated_at)}`;
}

function by(editor: string | null): string {
  return editor ? `von ${editor} ` : "";
}

function suggestionName(suggestion: HideSuggestion): string {
  if (suggestion.kind === "list") return suggestion.list_id ?? "";
  return suggestion.person ? personName(suggestion.person) : "";
}

function suggestionDraft(suggestion: HideSuggestion): RuleDraft {
  if (suggestion.kind === "list") return { list_id: suggestion.list_id };
  return { person_id: suggestion.person?.person_id ?? null, person: suggestion.person };
}
