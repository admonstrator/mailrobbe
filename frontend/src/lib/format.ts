// Numbers, sizes and dates for German readers. Dates are shown in the browser's time zone; the
// API's filter days (date_from, date_to) are UTC days.

const LOCALE = "de-DE";

const integerFormat = new Intl.NumberFormat(LOCALE);
const decimalFormat = new Intl.NumberFormat(LOCALE, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const percentFormat = new Intl.NumberFormat(LOCALE, {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/** 412318 -> "412.318" */
export function formatNumber(value: number): string {
  return integerFormat.format(value);
}

/** 0.651 -> "65,1 %" */
export function formatPercent(fraction: number): string {
  return percentFormat.format(fraction);
}

const KIB = 1024;
const MIB = 1024 ** 2;
const GIB = 1024 ** 3;

/** Sizes 1024-based: "512 B", "184 KB", "1,2 MB", "4,0 GB". */
export function formatBytes(bytes: number): string {
  if (bytes < KIB) return `${formatNumber(bytes)} B`;
  if (Math.round(bytes / KIB) < KIB) return `${formatNumber(Math.round(bytes / KIB))} KB`;
  if (Math.round((bytes / MIB) * 10) < KIB * 10) return `${decimalFormat.format(bytes / MIB)} MB`;
  return `${decimalFormat.format(bytes / GIB)} GB`;
}

/** Seconds as a short duration: "45 s", "30 min", "12 h", "7 Tage". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  const days = Math.round(seconds / 86400);
  return days === 1 ? "1 Tag" : `${days} Tage`;
}

/** A remaining time to the minute: "unter 1 min", "40 min", "1 h 40 min", "26 h". */
export function formatRemaining(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return "unter 1 min";
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  const hours = `${Math.floor(minutes / 60)} h`;
  return rest ? `${hours} ${rest} min` : hours;
}

/** An elapsed time to the second: "unter 1 s", "12 s", "3 min 7 s", "1 h 5 min". */
export function formatElapsed(seconds: number): string {
  const whole = Math.floor(seconds);
  if (whole < 1) return "unter 1 s";
  if (whole < 60) return `${whole} s`;
  if (whole < 3600) {
    const rest = whole % 60;
    const minutes = `${Math.floor(whole / 60)} min`;
    return rest ? `${minutes} ${rest} s` : minutes;
  }
  const rest = Math.floor((whole % 3600) / 60);
  const hours = `${Math.floor(whole / 3600)} h`;
  return rest ? `${hours} ${rest} min` : hours;
}

type Parts = Record<Intl.DateTimeFormatPartTypes, string>;

function partsOf(format: Intl.DateTimeFormat, date: Date): Parts {
  const parts = {} as Parts;
  for (const part of format.formatToParts(date)) parts[part.type] = part.value;
  return parts;
}

const dateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

/** "18.10.2026 14:32", with seconds "18.10.2026 14:32:07" */
export function formatDateTime(iso: string, seconds = false): string {
  const p = partsOf(dateTimeFormat, new Date(iso));
  const time = seconds ? `${p.hour}:${p.minute}:${p.second}` : `${p.hour}:${p.minute}`;
  return `${p.day}.${p.month}.${p.year} ${time}`;
}

/** "Sa, 18.10.2026 14:32:07" */
export function formatDateTimeLong(iso: string): string {
  const p = partsOf(dateTimeFormat, new Date(iso));
  const weekday = p.weekday.replace(/\.$/, "");
  return `${weekday}, ${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}:${p.second}`;
}

/** "18.10.", or "18.10.2025" when the year differs from referenceIso's. */
export function formatShortDate(iso: string, referenceIso?: string | null): string {
  const p = partsOf(dateTimeFormat, new Date(iso));
  const sameYear = !referenceIso || partsOf(dateTimeFormat, new Date(referenceIso)).year === p.year;
  return sameYear ? `${p.day}.${p.month}.` : `${p.day}.${p.month}.${p.year}`;
}

/** The local calendar day as "2014-03-02". */
export function formatIsoDay(iso: string): string {
  const p = partsOf(dateTimeFormat, new Date(iso));
  return `${p.year}-${p.month}-${p.day}`;
}

/** The UTC day of an ISO time as "2014-03-02", the unit of the API's date filters. */
export function utcDay(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

/** "18.10.2026" for a "2026-10-18" day. */
export function formatDay(day: string): string {
  const [year, month, date] = day.split("-");
  return `${date}.${month}.${year}`;
}

/** The local calendar day of an ISO time as "18.10.2026". */
export function formatDate(iso: string): string {
  return formatDay(formatIsoDay(iso));
}

const nearFormat = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
const relativeFormat = new Intl.RelativeTimeFormat(LOCALE, { numeric: "always" });

/** Calendar distance from now: "heute", "gestern", "vor 2 Tagen", "vor 3 Monaten", "vor 2 Jahren". */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(then) - startOfDay(now)) / 86_400_000);
  if (Math.abs(days) <= 1) return nearFormat.format(days, "day");
  if (Math.abs(days) < 31) return relativeFormat.format(days, "day");
  const months = (then.getFullYear() - now.getFullYear()) * 12 + (then.getMonth() - now.getMonth());
  if (Math.abs(months) < 12) return relativeFormat.format(months, "month");
  return relativeFormat.format(Math.trunc(months / 12), "year");
}
