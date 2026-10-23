// The short date of a row in a list like a mail program's (D335), in the browser's time zone.

const LOCALE = "de-DE";

const timeFormat = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit" });
const dayMonthFormat = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "long" });
const fullFormat = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const sameDay = (a: Date, b: Date) =>
  a.getFullYear() === b.getFullYear() &&
  a.getMonth() === b.getMonth() &&
  a.getDate() === b.getDate();

/** "14:32" today, "24. Juni" this year, "24.06.2024" in another year. */
export function formatListDate(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (sameDay(date, now)) return timeFormat.format(date);
  if (date.getFullYear() === now.getFullYear()) return dayMonthFormat.format(date);
  return fullFormat.format(date);
}
