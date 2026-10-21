// Amounts typed by hand (the mail list's "Betrag ab", the entity list's value range): German
// notation first, since the screens are German, with the English decimal point as a fallback.

/** The value of text: "10.000", "10000", "10 000", "10.000,50", "1,5" and "2.5" are read, a
 *  currency sign or code around it is ignored; null for an empty field, undefined for text that
 *  is no amount. */
export function parseAmount(text: string): number | null | undefined {
  const bare = text
    .replace(/\s/g, "") // \s covers the no-break spaces of copied German numbers
    .replace(/^(?:€|EUR|USD|CHF|GBP|DM|DEM|\$|£)|(?:€|EUR|USD|CHF|GBP|DM|DEM|\$|£)$/gi, "");
  if (bare === "") return null;
  let normal: string;
  if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(bare)) normal = bare.replace(/\./g, "").replace(",", ".");
  else if (/^\d+(,\d+)?$/.test(bare)) normal = bare.replace(",", ".");
  else if (/^\d+\.\d+$/.test(bare)) normal = bare;
  else return undefined;
  const value = Number(normal);
  return Number.isFinite(value) ? value : undefined;
}

/** A value from the URL: a plain non-negative decimal as the API takes it, else null. */
export function amountParam(value: string | null): number | null {
  if (value === null || !/^\d{1,15}(\.\d+)?$/.test(value)) return null;
  return Number(value);
}
