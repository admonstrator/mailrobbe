// The search words of a document search marked in a snippet (D74). The backend cuts the snippet
// around the first place one of the words occurs as typed; the browser marks every occurrence.

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

/** text cut into parts, marked where one of terms occurs in any case; the longest term wins
 *  where two start at the same place. */
export function highlightParts(text: string, terms: string[]): TextPart[] {
  if (terms.length === 0) return [{ text, mark: false }];
  const pattern = [...terms]
    .sort((a, b) => b.length - a.length)
    .map(escape)
    .join("|");
  const parts: TextPart[] = [];
  let last = 0;
  for (const match of text.matchAll(new RegExp(pattern, "giu"))) {
    const start = match.index;
    if (start > last) parts.push({ text: text.slice(last, start), mark: false });
    parts.push({ text: match[0], mark: true });
    last = start + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), mark: false });
  return parts;
}
