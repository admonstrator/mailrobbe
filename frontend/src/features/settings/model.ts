// What the page "Einstellungen" edits (D313): the draft of changed fields and the values a save
// sends. A field holds text while it is typed; numbers are read from it only when saving.

import type { SettingInfo, SettingValue } from "../../api/types";
import { formatBytes, formatNumber } from "../../lib/format";

export const MIB = 1024 ** 2;

/** The changed fields by name: their text or on/off, or null for "Zurücksetzen". */
export type Draft = Record<string, string | boolean | null>;

/** What a field shows: the draft, the value a reset brings back, or the current value. */
export function fieldValue(item: SettingInfo, draft: Draft): string | boolean {
  const changed = draft[item.name];
  if (changed === null) return asField(item, item.base);
  if (changed !== undefined) return changed;
  return asField(item, item.value);
}

function asField(item: SettingInfo, value: SettingValue): string | boolean {
  if (item.kind === "boolean") return value === true;
  if (item.kind === "secret" || value === null) return "";
  if (item.kind === "bytes") return String(Math.round((Number(value) / MIB) * 100) / 100);
  return String(value);
}

/** The value of a field's text; undefined when it is no number of the kind. */
function parse(item: SettingInfo, field: string | boolean): SettingValue | undefined {
  if (typeof field === "boolean") return field;
  const text = field.trim();
  if (item.kind === "integer") return /^-?\d+$/.test(text) ? Number(text) : undefined;
  if (item.kind === "number" || item.kind === "bytes") {
    const number = text === "" ? NaN : Number(text.replace(",", "."));
    if (!Number.isFinite(number)) return undefined;
    return item.kind === "bytes" ? Math.round(number * MIB) : number;
  }
  return text;
}

/** What a save sends (only what differs from now, null for a reset of a stored value) and the
 *  fields whose text is no number. */
export function changes(items: SettingInfo[], draft: Draft) {
  const values: Record<string, SettingValue> = {};
  const invalid: string[] = [];
  for (const item of items) {
    const field = draft[item.name];
    if (field === undefined) continue;
    if (field === null) {
      if (item.source === "stored") values[item.name] = null;
      continue;
    }
    if (item.kind === "secret") {
      if (field !== "") values[item.name] = field; // empty keeps the key
      continue;
    }
    const value = parse(item, field);
    if (value === undefined) invalid.push(item.name);
    else if (value !== item.value) values[item.name] = value;
  }
  return { values, invalid };
}

/** A value as the page names it: a size in MB, on or off, the choice's label, "leer". */
export function formatSetting(
  item: SettingInfo,
  value: SettingValue,
  choices?: Record<string, string>,
): string {
  if (item.kind === "secret") return item.secret_set ? "gesetzt" : "keiner";
  if (value === null || value === "") return "leer";
  if (typeof value === "boolean") return value ? "an" : "aus";
  if (item.kind === "bytes") return formatBytes(Number(value));
  if (typeof value === "number") return formatNumber(value);
  return choices?.[value] ?? value;
}
