// Search words marked in a text: in a document's snippet (D74), whose place the backend finds
// with the words as typed, and in a mail and its attachments (D79), where the words beginning
// with one of the query's German stems are marked too, the forms the full text search finds.

/** The words of q to mark: quoted phrases as a whole, the rest word by word, leaving out OR and
 *  negated words and phrases (websearch_to_tsquery syntax). Punctuation around a word is not part
 *  of it. */
export function highlightTerms(q: string): string[] {
  const terms: string[] = [];
  for (const match of q.matchAll(/(-?)"([^"]*)"?|(\S+)/g)) {
    const [, minus, phrase, word] = match;
    if (phrase !== undefined) {
      if (!minus && phrase.trim()) terms.push(phrase.trim());
      continue;
    }
    if (word.startsWith("-") || /^or$/i.test(word)) continue;
    const bare = word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
    if (bare) terms.push(bare);
  }
  return [...new Set(terms)];
}

export interface TextPart {
  text: string;
  mark: boolean;
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const MIN_STEM = 4; // shorter stems mark only a word that is the stem (EU, not Europa)
const WORD = /[\p{L}\p{N}]+/gu;

/** A word as PostgreSQL's German stems are written: lower case, umlauts as their base letter,
 *  ß as ss. */
function folded(word: string): string {
  return word
    .toLowerCase()
    .replace(/ä/g, "a")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u")
    .replace(/ß/g, "ss");
}

/** text cut into parts, marked where one of terms occurs in any case (the longest term wins
 *  where two start at the same place) and over each word that begins with one of stems. */
export function highlightParts(text: string, terms: string[], stems: string[] = []): TextPart[] {
  const ranges: [number, number][] = [];
  if (terms.length > 0) {
    const pattern = [...terms]
      .sort((a, b) => b.length - a.length)
      .map(escape)
      .join("|");
    for (const match of text.matchAll(new RegExp(pattern, "giu"))) {
      ranges.push([match.index, match.index + match[0].length]);
    }
  }
  if (stems.length > 0) {
    for (const match of text.matchAll(WORD)) {
      const word = folded(match[0]);
      const found = stems.some((stem) =>
        stem.length >= MIN_STEM ? word.startsWith(stem) : word === stem,
      );
      if (found) ranges.push([match.index, match.index + match[0].length]);
    }
  }
  ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
  const parts: TextPart[] = [];
  let last = 0;
  for (const [start, end] of ranges) {
    if (end <= last) continue;
    const from = Math.max(start, last);
    if (from > last) parts.push({ text: text.slice(last, from), mark: false });
    const previous = parts.at(-1);
    if (previous?.mark && from === last) previous.text += text.slice(from, end);
    else parts.push({ text: text.slice(from, end), mark: true });
    last = end;
  }
  if (last < text.length || parts.length === 0) parts.push({ text: text.slice(last), mark: false });
  return parts;
}

/** The number of marked parts. */
export function markCount(parts: TextPart[]): number {
  return parts.filter((part) => part.mark).length;
}
