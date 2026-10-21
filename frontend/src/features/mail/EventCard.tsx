import { Link } from "react-router";

import { useMailPage } from "../../api/queries";
import type { CalendarAttendee, CalendarEventInfo, MailListItem } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDate, formatDay, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { EVENT_LABELS } from "../mails/chips";
import { DEFAULT_LIST_STATE, listSearch, withFilters } from "../mails/listState";
import styles from "./EventCard.module.css";

/** The answers of attendees (PARTSTAT) in German; another value shows as written. */
export const ANSWER_LABELS: Record<string, string> = {
  ACCEPTED: "zugesagt",
  DECLINED: "abgesagt",
  TENTATIVE: "vorläufig",
  "NEEDS-ACTION": "offen",
  DELEGATED: "delegiert",
};

const ANSWER_CLASSES: Record<string, string | undefined> = {
  ACCEPTED: styles.accepted,
  DECLINED: styles.declined,
  TENTATIVE: styles.tentative,
};

const ROLE_LABELS: Record<string, string> = {
  "OPT-PARTICIPANT": "optional",
  "NON-PARTICIPANT": "zur Information",
};

/** Attendees shown at once; the others behind "und n weitere". */
const ATTENDEES_SHOWN = 12;
/** The other mails of an event the card lists; the mail list has them all. */
const OTHERS_SHOWN = 5;

export function answerText(partstat: string | null): string | null {
  if (!partstat) return null;
  return ANSWER_LABELS[partstat.toUpperCase()] ?? partstat;
}

/** The mail list of the mails with an event of this UID (D155). */
export function eventMailsHref(uid: string): string {
  return `/mails?${listSearch(withFilters(DEFAULT_LIST_STATE, { event_uid: uid }))}`;
}

// Times ----------------------------------------------------------------------------------------

const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

function dayParts(day: string): [number, number, number] {
  const [year, month, date] = day.split("-").map(Number);
  return [year, month, date];
}

/** "Di, 04.05.2021" for the day "2021-05-04". */
function dayText(day: string): string {
  const [year, month, date] = dayParts(day);
  return `${WEEKDAYS[new Date(Date.UTC(year, month - 1, date)).getUTCDay()]}, ${formatDay(day)}`;
}

function previousDay(day: string): string {
  const [year, month, date] = dayParts(day);
  return new Date(Date.UTC(year, month - 1, date - 1)).toISOString().slice(0, 10);
}

/** A wall time "2021-05-04T10:00:00" as "Di, 04.05.2021, 10:00", with the end beside it:
 *  "–11:00" on the same day, else with its own day. */
function spanText(start: string, end: string | null): string {
  const [day, time = ""] = start.split("T");
  const head = `${dayText(day)}, ${time.slice(0, 5)}`;
  if (!end || end.slice(0, 16) === start.slice(0, 16)) return head;
  const [endDay, endTime = ""] = end.split("T");
  return endDay === day
    ? `${head}–${endTime.slice(0, 5)}`
    : `${head} – ${dayText(endDay)}, ${endTime.slice(0, 5)}`;
}

/** All-day events by their days; DTEND is the day after the last. */
function daysText(start: string, end: string | null): string {
  const first = start.slice(0, 10);
  const last = end ? previousDay(end.slice(0, 10)) : first;
  return last > first ? `${dayText(first)} – ${dayText(last)}` : dayText(first);
}

const berlinFormat = new Intl.DateTimeFormat("de-DE", {
  timeZone: "Europe/Berlin",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** The wall time of an instant in Berlin, as "2021-05-04T12:00". */
function inBerlin(iso: string): string {
  const parts: Partial<Record<Intl.DateTimeFormatPartTypes, string>> = {};
  for (const part of berlinFormat.formatToParts(new Date(iso))) parts[part.type] = part.value;
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export interface EventTime {
  written: string; // as the calendar writes it
  zone: string | null; // its TZID, "UTC", or null for a floating time and all-day events
  berlin: string | null; // the same in Berlin, when the instant is known and the wall time differs
}

/** When an event takes place (D155): as written, and in Berlin when that is another time. */
export function eventTime(event: CalendarEventInfo): EventTime | null {
  if (!event.starts_local) return null;
  if (event.all_day) {
    return { written: daysText(event.starts_local, event.ends_local), zone: null, berlin: null };
  }
  const written = spanText(event.starts_local, event.ends_local);
  const berlin = event.starts_at
    ? spanText(inBerlin(event.starts_at), event.ends_at && inBerlin(event.ends_at))
    : null;
  return { written, zone: event.time_zone, berlin: berlin === written ? null : berlin };
}

/** The start for lists: all-day as the day, else in Berlin when the instant is known. */
export function eventStart(event: CalendarEventInfo): string | null {
  if (!event.starts_local) return null;
  if (event.all_day) return dayText(event.starts_local.slice(0, 10));
  return spanText(event.starts_at ? inBerlin(event.starts_at) : event.starts_local, null);
}

// Recurrence -----------------------------------------------------------------------------------

const FREQUENCIES: Record<string, [string, string]> = {
  DAILY: ["täglich", "Tage"],
  WEEKLY: ["wöchentlich", "Wochen"],
  MONTHLY: ["monatlich", "Monate"],
  YEARLY: ["jährlich", "Jahre"],
};

const RULE_DAYS: Record<string, string> = {
  MO: "Mo",
  TU: "Di",
  WE: "Mi",
  TH: "Do",
  FR: "Fr",
  SA: "Sa",
  SU: "So",
};

/** An RRULE in words when it is a simple one ("wöchentlich am Di, 6-mal"), else as written. */
export function recurrenceText(rule: string): string {
  const parts = new Map<string, string>();
  for (const part of rule.split(";")) {
    const [key, value = ""] = part.split("=");
    if (key.trim()) parts.set(key.trim().toUpperCase(), value.trim().toUpperCase());
  }
  const frequency = FREQUENCIES[parts.get("FREQ") ?? ""];
  const interval = parts.get("INTERVAL") ?? "1";
  if (!frequency || !/^[1-9]\d*$/.test(interval)) return rule;
  let text = interval === "1" ? frequency[0] : `alle ${interval} ${frequency[1]}`;
  for (const [key, value] of parts) {
    if (key === "FREQ" || key === "INTERVAL" || key === "WKST") continue;
    if (key === "BYDAY" && parts.get("FREQ") === "WEEKLY") {
      const days = value.split(",").map((day) => RULE_DAYS[day]);
      if (days.some((day) => day === undefined)) return rule;
      text += ` am ${days.join(", ")}`;
    } else if (key === "BYMONTHDAY" && parts.get("FREQ") === "MONTHLY" && /^\d{1,2}$/.test(value)) {
      text += ` am ${Number(value)}.`;
    } else if (key === "COUNT" && /^\d+$/.test(value)) {
      text += `, ${value}-mal`;
    } else if (key === "UNTIL" && /^\d{8}/.test(value)) {
      text += `, bis ${formatDay(`${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`)}`;
    } else {
      return rule;
    }
  }
  return text;
}

// Card -----------------------------------------------------------------------------------------

/** "Termin" (D155): the calendar events of a mail, one block each: kind and summary, the time
 *  as written and in Berlin, place, recurrence, organiser and attendees with their answers, the
 *  description folded, and the other mails of the same UID. Nothing for a mail without one. */
export function EventCard({
  events,
  mailId,
  mailHref,
}: {
  events: CalendarEventInfo[];
  mailId: number;
  mailHref: (id: number) => string;
}) {
  if (events.length === 0) return null;
  return (
    <Card aria-labelledby="mail-events-title">
      <CardTitle id="mail-events-title">
        {events.length === 1 ? "Termin" : `Termine (${formatNumber(events.length)})`}
      </CardTitle>
      {events.map((event) => (
        <EventBlock key={event.id} event={event} mailId={mailId} mailHref={mailHref} />
      ))}
    </Card>
  );
}

function EventBlock({
  event,
  mailId,
  mailHref,
}: {
  event: CalendarEventInfo;
  mailId: number;
  mailHref: (id: number) => string;
}) {
  const time = eventTime(event);
  const cancelled = event.kind === "cancel";
  const attendees = event.attendees;
  return (
    <article className={cx(styles.event, cancelled && styles.cancelled)}>
      <p className={styles.head}>
        <span className={cx(styles.kind, styles[event.kind])}>{EVENT_LABELS[event.kind]}</span>
        <span className={styles.summary}>{event.summary || "(ohne Titel)"}</span>
        {event.kind === "request" && event.sequence !== null && event.sequence > 0 && (
          <span className={styles.sequence} title={`SEQUENCE:${event.sequence}`}>
            {`geändert (Fassung ${event.sequence + 1})`}
          </span>
        )}
      </p>
      {cancelled && (
        <p className={styles.notice} role="note">
          Abgesagt: Dieser Termin wurde abgesagt.
        </p>
      )}
      <dl className={styles.facts}>
        <dt>Wann</dt>
        <dd>
          {time === null ? (
            <span className={styles.muted}>unbekannt</span>
          ) : (
            <>
              <span>
                {time.written}
                {event.all_day ? (
                  <span className={styles.muted}> (ganztägig)</span>
                ) : (
                  <span className={styles.muted}> ({time.zone ?? "ohne Zeitzone"})</span>
                )}
              </span>
              {time.berlin && <span className={styles.berlin}>{`in Berlin: ${time.berlin}`}</span>}
            </>
          )}
        </dd>
        {event.location && (
          <>
            <dt>Wo</dt>
            <dd>{event.location}</dd>
          </>
        )}
        {event.recurrence && (
          <>
            <dt>Wiederholung</dt>
            <dd title={event.recurrence}>{recurrenceText(event.recurrence)}</dd>
          </>
        )}
        {event.organizer && (
          <>
            <dt>Organisiert von</dt>
            <dd>
              <Participant who={event.organizer} />
            </dd>
          </>
        )}
        {attendees.length > 0 && (
          <>
            <dt>{event.kind === "reply" ? "Antwort von" : "Teilnehmende"}</dt>
            <dd>
              <Attendees attendees={attendees} />
            </dd>
          </>
        )}
      </dl>
      {event.description && (
        <details className={styles.description}>
          <summary>Beschreibung</summary>
          <p>{event.description}</p>
        </details>
      )}
      {event.uid !== null && event.uid_mails > 1 && (
        <OtherMails uid={event.uid} total={event.uid_mails} mailId={mailId} mailHref={mailHref} />
      )}
    </article>
  );
}

function Attendees({ attendees }: { attendees: CalendarAttendee[] }) {
  const rest = attendees.slice(ATTENDEES_SHOWN);
  const list = (people: CalendarAttendee[]) => (
    <ul className={styles.people}>
      {people.map((who, index) => (
        <li key={`${who.email ?? ""}-${index}`}>
          <Participant who={who} />
        </li>
      ))}
    </ul>
  );
  return (
    <>
      {list(attendees.slice(0, ATTENDEES_SHOWN))}
      {rest.length > 0 && (
        <details className={styles.more}>
          <summary>{`und ${formatNumber(rest.length)} weitere`}</summary>
          {list(rest)}
        </details>
      )}
    </>
  );
}

/** A name linking to the person when the address is one of a person's, the address, the role
 *  when it is not a plain one, and the answer. */
function Participant({ who }: { who: CalendarAttendee }) {
  const shown = who.person ? personName(who.person) : who.name || who.email || "(ohne Adresse)";
  const role = who.role ? ROLE_LABELS[who.role.toUpperCase()] : undefined;
  const answer = answerText(who.partstat);
  return (
    <span className={styles.participant}>
      {who.person ? <PersonLink person={who.person} /> : <span>{shown}</span>}
      {who.email && who.email !== shown && (
        <span className={styles.muted}>{` <${who.email}>`}</span>
      )}
      {role && <span className={styles.muted}>{` (${role})`}</span>}
      {answer && (
        <span className={cx(styles.answer, ANSWER_CLASSES[who.partstat?.toUpperCase() ?? ""])}>
          {answer}
        </span>
      )}
    </span>
  );
}

/** "Weitere Mails zu diesem Termin": the newest other mails of the UID and the list of all. */
function OtherMails({
  uid,
  total,
  mailId,
  mailHref,
}: {
  uid: string;
  total: number;
  mailId: number;
  mailHref: (id: number) => string;
}) {
  const page = useMailPage({ event_uid: uid, limit: OTHERS_SHOWN + 1 });
  const others = (page.data?.items ?? []).filter((mail) => mail.id !== mailId);
  return (
    <div className={styles.others}>
      <h3 className={styles.othersTitle}>Weitere Mails zu diesem Termin</h3>
      {page.isPending ? (
        <Spinner label="Mails werden geladen" />
      ) : page.isError ? (
        <p className={styles.muted}>Die Mails konnten nicht geladen werden.</p>
      ) : (
        <ul className={styles.mails}>
          {others.slice(0, OTHERS_SHOWN).map((mail) => (
            <OtherMail key={mail.id} mail={mail} href={mailHref(mail.id)} />
          ))}
        </ul>
      )}
      <Link to={eventMailsHref(uid)} className={styles.all}>
        {`Alle ${formatNumber(total)} Mails zu diesem Termin in der Mailliste`}
      </Link>
    </div>
  );
}

function OtherMail({ mail, href }: { mail: MailListItem; href: string }) {
  const sender = mail.sender ? personName(mail.sender) : "(unbekannt)";
  return (
    <li className={styles.mail}>
      {mail.event && (
        <span className={cx(styles.kind, styles.small, styles[mail.event])}>
          {EVENT_LABELS[mail.event]}
        </span>
      )}
      <Link to={href}>{mail.subject || "(kein Betreff)"}</Link>
      <span className={styles.muted}>
        {sender}
        {mail.date && ` · ${formatDate(mail.date)}`}
      </span>
    </li>
  );
}
