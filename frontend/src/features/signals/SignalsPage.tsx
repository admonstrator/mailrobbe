import { useEffect, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import { withQuery } from "../../api/client";
import { useSignals } from "../../api/queries";
import type { SignalGroup, SignalInfo, SignalOverview, SilentPerson } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { PersonLink, personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { mailsText } from "../entities/labels";
import { personLabel } from "../persons/labels";
import { timelinePath } from "../timeline/buckets";
import {
  GROUP_NAMES,
  joinList,
  personSignalHref,
  shareText,
  SIGNAL_NAMES,
  signalAnchor,
  signalMailsHref,
  signalName,
  signalRule,
  signalTimelineHref,
  silentMonth,
  UNAVAILABLE_TEXT,
} from "./labels";
import styles from "./SignalsPage.module.css";

/** The groups of mail signals with a card of their own, in display order; word fields and
 *  persons follow. */
const MAIL_GROUPS: readonly SignalGroup[] = ["addresses", "recipients", "time", "attachments"];

/** The overview "Signale" (D137): what signals are and how to search with them, the rules'
 *  settings and when the last signals phase ran, then every signal with its rule, figures,
 *  links and senders, the word fields, and the persons fallen silent. */
export function SignalsPage() {
  const overview = useSignals();
  const { hash } = useLocation();
  const target = decodeURIComponent(hash.slice(1));
  const loaded = overview.data !== undefined;

  // A facet's "›" leads to its signal's entry, which exists once the figures are there.
  useEffect(() => {
    if (loaded && target) document.getElementById(target)?.scrollIntoView?.({ block: "start" });
  }, [loaded, target]);

  return (
    <main className={styles.page}>
      <title>Signale · Mailrobbe</title>
      <h1 className={styles.title}>Signale</h1>
      <Intro />
      {overview.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Signale werden geladen" />
        </Card>
      ) : overview.isError ? (
        <Card>
          <ErrorState
            title="Die Signale konnten nicht geladen werden."
            actions={<Button onClick={() => void overview.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <Overview overview={overview.data} target={target} />
      )}
    </main>
  );
}

const INTRO_KEY = "mailrobbe.signals-intro";

function loadIntroOpen(): boolean {
  try {
    return localStorage.getItem(INTRO_KEY) !== "closed";
  } catch {
    return true; // storage blocked: open
  }
}

function saveIntroOpen(open: boolean): void {
  try {
    localStorage.setItem(INTRO_KEY, open ? "open" : "closed");
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** What signals are and how to search with them: open until folded, then folded on later
 *  visits too. */
function Intro() {
  const [open, setOpen] = useState(loadIntroOpen);
  return (
    <details
      className={styles.introBox}
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        if (next === open) return;
        setOpen(next);
        saveIntroOpen(next);
      }}
    >
      <summary className={styles.introSummary}>Was Signale sind und wie Sie damit suchen</summary>
      <div className={styles.intro}>
        <section className={styles.introPart} aria-labelledby="signals-what">
          <h2 id="signals-what" className={styles.introTitle}>
            Was Signale sind
          </h2>
          <p>
            Einfache Regeln, die auf Mails zeigen, die sich zu lesen lohnen können: eine private
            Adresse, eine Blindkopie, eine Mail mitten in der Nacht, ein Begriff aus einem
            Recherchethema, eine Person, von der plötzlich nichts mehr kommt. Jede Regel steht unten
            in einem Satz.
          </p>
          <p>
            Signale bewerten nichts und beweisen nichts. Viele haben harmlose Gründe; ob eine Mail
            zählt, zeigt erst das Lesen.
          </p>
        </section>
        <section className={styles.introPart} aria-labelledby="signals-how">
          <h2 id="signals-how" className={styles.introTitle}>
            So suchen Sie damit
          </h2>
          <ol className={styles.steps}>
            <li>Ein Signal wählen: hier über „Mails“ oder in der Mailliste unter „Signale“.</li>
            <li>
              Mit der Suche, einer Person, einem Zeitraum oder einem Thema verbinden; mehrere
              Signale gelten zusammen.
            </li>
            <li>Auf der Zeitachse sehen, wann es sich häuft.</li>
            <li>
              Die Mails öffnen und lesen. Jede Mail sagt unter „Warum fällt diese Mail auf“, was auf
              sie zutrifft.
            </li>
          </ol>
        </section>
      </div>
    </details>
  );
}

function Overview({ overview, target }: { overview: SignalOverview; target: string }) {
  const computed = overview.computed_at !== null;
  const wording = overview.signals.filter((info) => info.group === "wording");
  return (
    <>
      <Settings overview={overview} />
      <div className={styles.groups}>
        {MAIL_GROUPS.map((group) => (
          <SignalGroupCard
            key={group}
            group={group}
            signals={overview.signals.filter((info) => info.group === group)}
            overview={overview}
            target={target}
          >
            {group === "time" && (
              <p className={styles.groupNote}>
                {`Ortszeit ${overview.settings.timezone}: Auch eine im Ausland geschriebene Mail zeigt die Stunde dieser Zone.`}
              </p>
            )}
            {group === "attachments" && (
              <p className={styles.groupNote}>
                Welche Kennwörter gefunden wurden und was sie geöffnet haben, zeigen die Anhänge mit
                dem Filter{" "}
                <Link to={withQuery("/anhaenge", { protection: ["locked", "open"] })}>
                  „Verschlüsselt“
                </Link>
                .
              </p>
            )}
          </SignalGroupCard>
        ))}
        {wording.length > 0 && (
          <SignalGroupCard group="wording" signals={wording} overview={overview} target={target}>
            <p className={styles.groupNote}>
              {signalRule(wording[0].key, overview.settings)}{" "}
              <Link to="/akten?tab=themen">Die Wortfelder stehen unter Akten › Themen.</Link>
            </p>
          </SignalGroupCard>
        )}
      </div>
      <SilentCard overview={overview} computed={computed} target={target} />
    </>
  );
}

/** The settings the rules read and when they were applied last (D131 to D135). */
function Settings({ overview }: { overview: SignalOverview }) {
  const { settings, computed_at: computedAt } = overview;
  return (
    <Card aria-labelledby="signals-settings" className={styles.settings}>
      <h2 id="signals-settings" className={styles.cardTitle}>
        Regeln und Stand
      </h2>
      <div className={styles.status}>
        {computedAt === null ? (
          <p className={styles.notice}>
            Noch nicht berechnet. Die Signale entstehen beim nächsten Import, ohne dass Mails neu
            eingelesen werden. <Link to="/import">Zum Import</Link>
          </p>
        ) : (
          <p className={styles.computed}>
            {`Berechnet beim Import am ${formatDateTime(computedAt)}, über ${mailsText(overview.mails)} ohne Duplikate.`}
          </p>
        )}
        {computedAt !== null && overview.outdated && (
          <p className={styles.notice}>
            Diese Zahlen entstanden unter anderen Regeln oder Wortfeldern als den jetzigen. Der
            nächste <Link to="/import">Import</Link> berechnet sie neu.
          </p>
        )}
      </div>
      <dl className={styles.rules}>
        <div className={cx(styles.setting, settings.internal_domains.length === 0 && styles.wide)}>
          <dt>Interne Domains</dt>
          <dd>
            <InternalDomains overview={overview} />
          </dd>
        </div>
        <div className={cx(styles.setting, !settings.timezone_known && styles.wide)}>
          <dt>Zeitzone</dt>
          <dd>
            {settings.timezone}
            {!settings.timezone_known && (
              <span className={cx(styles.notice, styles.inline)}>
                PostgreSQL kennt diese Zeitzone nicht. Der nächste Import kann die Signale erst
                berechnen, wenn die Einstellungen eine gültige Zone nennen, etwa Europe/Berlin.
              </span>
            )}
          </dd>
        </div>
        <div className={styles.setting}>
          <dt>Private Mailanbieter</dt>
          <dd>{`${formatNumber(settings.private_domains)} Domains`}</dd>
        </div>
        <div className={styles.setting}>
          <dt>Nachts</dt>
          <dd>{`${settings.night_from} bis ${settings.night_to} Uhr`}</dd>
        </div>
        <div className={styles.setting}>
          <dt>Viele Empfänger</dt>
          <dd>{`ab ${formatNumber(settings.many_recipients)} Adressen`}</dd>
        </div>
        <div className={styles.setting}>
          <dt>Weiterleitung</dt>
          <dd>{settings.forward_prefixes.map((prefix) => `${prefix}:`).join(" ")}</dd>
        </div>
      </dl>
      <p className={styles.footnote}>
        Die Anbieter, Uhrzeiten, die Schwelle und die Präfixe stehen in themes.toml unter [signals],
        die Domains und die Zeitzone unter <Link to="/einstellungen">Einstellungen</Link>.
        Änderungen gelten ab dem nächsten „Import starten“. Mails automatischer Absender wie
        Newsletter tragen nur die Wortfelder.
      </p>
    </Card>
  );
}

/** The internal domains, or why three signals are off without them and which sender domains
 *  could be the owner's (D131). */
function InternalDomains({ overview }: { overview: SignalOverview }) {
  const domains = overview.settings.internal_domains;
  if (domains.length > 0) return <>{domains.join(", ")}</>;
  const off = overview.signals
    .filter((info) => !info.available)
    .map((info) => signalName(info.key, info.theme));
  return (
    <div className={cx(styles.notice, styles.inline)}>
      <p>
        {off.length > 0
          ? `Nicht gesetzt: ${joinList(off)} ${off.length === 1 ? "ist" : "sind"} aus, bis die Einstellungen die eigenen Domains der Organisation nennen.`
          : "Nicht gesetzt."}
      </p>
      {overview.sender_domains.length > 0 && (
        <p>
          {"Als Hilfe die Absender-Domains mit den meisten Mails: "}
          {overview.sender_domains
            .map((domain) => `${domain.domain} (${formatNumber(domain.mails)})`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

function SignalGroupCard({
  group,
  signals,
  overview,
  target,
  children,
}: {
  group: SignalGroup;
  signals: SignalInfo[];
  overview: SignalOverview;
  target: string;
  children?: ReactNode;
}) {
  if (signals.length === 0) return null;
  const titleId = `signal-group-${group}`;
  return (
    <Card aria-labelledby={titleId}>
      <h2 id={titleId} className={styles.cardTitle}>
        {GROUP_NAMES[group]}
      </h2>
      {children}
      <ul className={styles.signals}>
        {signals.map((info) => (
          <SignalEntry
            key={info.key}
            info={info}
            overview={overview}
            targeted={signalAnchor(info.key) === target}
          />
        ))}
      </ul>
    </Card>
  );
}

function SignalEntry({
  info,
  overview,
  targeted,
}: {
  info: SignalInfo;
  overview: SignalOverview;
  targeted: boolean;
}) {
  const wording = info.group === "wording";
  const name = wording ? (info.theme ?? info.key) : signalName(info.key, info.theme);
  const computed = overview.computed_at !== null;
  const share = shareText(info.mails, overview.mails);
  return (
    <li
      id={signalAnchor(info.key)}
      className={cx(styles.signal, !info.available && styles.off, targeted && styles.target)}
    >
      <div className={styles.about}>
        <h3 className={styles.name}>{name}</h3>
        {!wording && <p className={styles.rule}>{signalRule(info.key, overview.settings)}</p>}
        {!info.available && <p className={styles.reason}>{UNAVAILABLE_TEXT}</p>}
      </div>
      {info.available && (
        <>
          <p className={styles.figures}>
            {computed ? (
              <>
                <span>
                  <strong>{formatNumber(info.mails)}</strong>
                  {` ${info.mails === 1 ? "Mail" : "Mails"}`}
                  {share && <span className={styles.share}>{` · ${share}`}</span>}
                </span>
                <span className={styles.persons}>
                  {`von ${formatNumber(info.persons)} ${info.persons === 1 ? "Person" : "Personen"} gesendet`}
                </span>
              </>
            ) : (
              <span className={styles.share}>noch nicht berechnet</span>
            )}
          </p>
          <p className={styles.links}>
            <Link
              to={signalMailsHref(info.key)}
              aria-label={`Mails mit ${signalName(info.key, info.theme)}`}
            >
              Mails
            </Link>
            <Link
              to={signalTimelineHref(info.key)}
              aria-label={`Zeitachse von ${signalName(info.key, info.theme)}`}
            >
              Zeitachse
            </Link>
          </p>
          {info.senders.length > 0 && <Senders info={info} />}
        </>
      )}
    </li>
  );
}

/** Who sent most mails with the signal (at most SIGNAL_SENDERS), each with those mails. */
function Senders({ info }: { info: SignalInfo }) {
  const name = signalName(info.key, info.theme);
  return (
    <div className={styles.senders}>
      <span className={styles.sendersLabel}>
        {info.persons > info.senders.length ? "Am häufigsten von" : "Von"}
      </span>
      <ul className={styles.senderList}>
        {info.senders.map(({ person, mails }) => (
          <li key={person.person_id}>
            <PersonLink person={person} />{" "}
            <Link
              to={personSignalHref(person.person_id, info.key)}
              className={styles.count}
              aria-label={`${mailsText(mails)} von ${personLabel(person)} mit ${name}`}
              title={`${mailsText(mails)} mit diesem Signal`}
            >
              {formatNumber(mails)}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The persons fallen silent (D134), most mails before their silence first. */
function SilentCard({
  overview,
  computed,
  target,
}: {
  overview: SignalOverview;
  computed: boolean;
  target: string;
}) {
  const { silent, silent_count: count } = overview;
  return (
    <Card aria-labelledby="signal-group-persons">
      <h2 id="signal-group-persons" className={styles.cardTitle}>
        {GROUP_NAMES.persons}
      </h2>
      <div
        id={signalAnchor("silent")}
        className={cx(styles.silentHead, signalAnchor("silent") === target && styles.target)}
      >
        <h3 className={styles.name}>{SIGNAL_NAMES.silent}</h3>
        <p className={styles.rule}>{signalRule("silent", overview.settings)}</p>
      </div>
      {!computed ? (
        <p className={styles.empty}>Noch nicht berechnet.</p>
      ) : silent.length === 0 ? (
        <p className={styles.empty}>Niemand ist nach dieser Regel verstummt.</p>
      ) : (
        <>
          <ul className={styles.silentList} aria-label="Verstummte Personen">
            {silent.map((entry) => (
              <SilentRow key={entry.person.person_id} entry={entry} />
            ))}
          </ul>
          {count > silent.length && (
            <p className={styles.footnote}>
              {`Gezeigt: ${formatNumber(silent.length)} von ${formatNumber(count)} Personen, die mit den meisten Mails davor zuerst.`}
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function SilentRow({ entry: { person, since, mails } }: { entry: SilentPerson }) {
  return (
    <li className={styles.silentRow}>
      <Link to={personPath(person.person_id)} className={styles.personName} title={person.email}>
        {personLabel(person)}
      </Link>
      <span className={styles.since}>{`verstummt seit ${silentMonth(since)}`}</span>
      <span className={styles.before}>{`${mailsText(mails)} in den sechs Monaten davor`}</span>
      <Link
        to={timelinePath({ person: [person.person_id] })}
        className={styles.timeline}
        aria-label={`Zeitachse von ${personLabel(person)}`}
      >
        Zeitachse
      </Link>
    </li>
  );
}
