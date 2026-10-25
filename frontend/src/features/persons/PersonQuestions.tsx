import { useState } from "react";
import { Link } from "react-router";

import { useAskPerson, useDiscardQuestion, usePersonQuestions } from "../../api/queries";
import type {
  PersonProfile,
  PersonQuestionItem,
  PersonQuestionPerson,
  PersonSummary,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { AiBusy } from "../ai/AiBusy";
import { aiErrorText, preworkText } from "../ai/labels";
import { PersonPicker } from "../timeline/PersonPicker";
import styles from "./PersonQuestions.module.css";

const FREE = "free";

/** A question with "Person A" and "Person B" replaced by the names the page shows. */
export function namedQuestion(
  question: string,
  person: PersonQuestionPerson | PersonProfile,
  other: { name: string | null; email: string } | null,
): string {
  return question
    .replaceAll("Person A", personName(person))
    .replaceAll("Person B", other ? personName(other) : "einer zweiten Person");
}

function runText(run: string): string {
  switch (run) {
    case "started":
      return "Ein KI-Lauf ist gestartet; die Antwort erscheint hier, sobald sie da ist.";
    case "running":
      return "Ein KI-Lauf ist schon unterwegs und nimmt die Frage als Nächstes dran.";
    case "busy":
      return "Vorgemerkt: Gerade läuft ein Import. Danach lässt sich der Lauf auf der Seite „KI“ starten.";
    default:
      return "Vorgemerkt.";
  }
}

/** The tab "KI fragen" of a person (D347): questions to choose from, one with a second person,
 *  or a question of one's own, and the questions asked before with their answers, kept for the
 *  next visit. What an answer needs first (summaries of the person's conversations, attachments
 *  read) is done first, first in the queue, and the notice says how long it takes (D348); an
 *  open question shows the time the AI has taken and is asked again every 3 s. */
export function PersonQuestions({ profile }: { profile: PersonProfile }) {
  const questions = usePersonQuestions(profile.id);
  const ask = useAskPerson(profile.id);
  const [template, setTemplate] = useState<string | null>(null);
  const [other, setOther] = useState<PersonSummary | null>(null);
  const [text, setText] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const view = questions.data;
  if (!view) return questions.isError ? null : <Spinner label="Wird geladen" />;

  const chosen = view.templates.find((item) => item.key === template);
  const ready =
    chosen !== undefined &&
    (!chosen.compare || other !== null) &&
    (chosen.key !== FREE || text.trim() !== "");
  const submit = () =>
    chosen &&
    ask.mutate(
      {
        template: chosen.key,
        other_id: chosen.compare ? other?.id : null,
        text: chosen.key === FREE ? text.trim() : null,
      },
      {
        onSuccess: (asked) => {
          const before = asked.question.prework && preworkText(asked.question.prework);
          setNotice([before, runText(asked.run)].filter(Boolean).join(" "));
          setTemplate(null);
          setText("");
        },
        onError: (error) => setNotice(aiErrorText(error)),
      },
    );

  return (
    <div className={styles.questions}>
      {!view.available ? (
        <p className={styles.note}>
          Für Fragen an die KI braucht es ein Textmodell auf diesem Rechner, siehe{" "}
          <Link to="/einstellungen">Einstellungen</Link>. Die Fragen schicken Namen und Inhalte nur
          an einen Dienst im eigenen Netz.
        </p>
      ) : (
        <section className={styles.ask} aria-label="Frage stellen">
          <p className={styles.note}>
            Die KI liest die Kennzahlen der Person, ihre häufigsten Kontakte und die
            Zusammenfassungen ihrer wichtigsten Gespräche. Fehlt davon etwas, wird es zuerst
            erstellt.
          </p>
          <div className={styles.templates} role="group" aria-label="Fragen">
            {view.templates.map((item) => (
              <button
                key={item.key}
                type="button"
                className={cx(styles.template, item.key === template && styles.chosen)}
                aria-pressed={item.key === template}
                title={item.question ? namedQuestion(item.question, profile, null) : undefined}
                onClick={() => setTemplate(item.key === template ? null : item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
          {chosen && (
            <div className={styles.form}>
              {chosen.compare && (
                <div className={styles.other}>
                  {other ? (
                    <span>
                      {`Zweite Person: ${personName(other)} `}
                      <Button size="xs" variant="link" onClick={() => setOther(null)}>
                        ändern
                      </Button>
                    </span>
                  ) : (
                    <PersonPicker chosen={[profile.id]} disabled={false} onPick={setOther} />
                  )}
                </div>
              )}
              {chosen.key === FREE ? (
                <textarea
                  className={styles.text}
                  aria-label="Eigene Frage"
                  placeholder={`Was möchtest du über ${personName(profile)} wissen?`}
                  maxLength={1000}
                  rows={3}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                />
              ) : (
                <p className={styles.question}>{namedQuestion(chosen.question, profile, other)}</p>
              )}
              <Button variant="ai" size="sm" disabled={!ready || ask.isPending} onClick={submit}>
                KI fragen
              </Button>
            </div>
          )}
          {notice && (
            <p className={styles.note} role="status">
              {notice}
            </p>
          )}
        </section>
      )}
      {view.questions.length === 0 ? (
        <p className={styles.note}>Noch keine Fragen zu dieser Person.</p>
      ) : (
        <ul className={styles.list} aria-label="Gestellte Fragen">
          {view.questions.map((item) => (
            <QuestionItem key={item.id} item={item} />
          ))}
        </ul>
      )}
    </div>
  );
}

function QuestionItem({ item }: { item: PersonQuestionItem }) {
  const discard = useDiscardQuestion();
  const open = item.status === "waiting" || item.status === "running";
  const before = item.prework && preworkText(item.prework);
  return (
    <li className={styles.item}>
      <p className={styles.asked}>{namedQuestion(item.question, item.person, item.other)}</p>
      {open && (
        <>
          <AiBusy
            what={
              item.open > 0
                ? `Vorarbeit läuft, noch ${formatNumber(item.open)} ${item.open === 1 ? "Aufgabe" : "Aufgaben"}`
                : item.status === "running"
                  ? "Die KI antwortet"
                  : "Vorgemerkt"
            }
            from={item.started_at ?? item.queued_at}
          />
          {before && item.open > 0 && <p className={styles.note}>{before}</p>}
        </>
      )}
      {item.answer && <p className={styles.answer}>{item.answer}</p>}
      {item.status === "failed" && (
        <p className={styles.warning}>{`Die Frage ist fehlgeschlagen: ${item.error ?? ""}`}</p>
      )}
      <p className={styles.meta}>
        {item.answer
          ? `Maschinell erzeugt · ${item.model ?? ""} · ${formatDateTime(item.finished_at ?? item.queued_at)} · aus ${formatNumber(item.contents ?? 0)} Zusammenfassungen`
          : `Gefragt ${formatDateTime(item.queued_at)}`}
        {item.status !== "running" && (
          <>
            {" · "}
            <Button
              size="xs"
              variant="link"
              disabled={discard.isPending}
              onClick={() => discard.mutate(item.id)}
            >
              {open ? "Zurückziehen" : "Verwerfen"}
            </Button>
          </>
        )}
      </p>
    </li>
  );
}
