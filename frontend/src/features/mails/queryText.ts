// Working with the search text q: removing a recognised term, finding the term an error names.

/** q without the exact substring raw (a QueryTerm's raw), spaces normalised. */
export function removeTerm(q: string, raw: string): string {
  const at = q.indexOf(raw);
  const rest = at < 0 ? q : q.slice(0, at) + " " + q.slice(at + raw.length);
  return rest.replace(/\s+/g, " ").trim();
}

/** The part of q an invalid_query message names: the longest operator token of q that the
 *  message quotes, else a quoted part of the message, else the whole message. */
export function invalidTerm(message: string, q: string): string {
  const tokens = (q.match(/[^\s"]*"[^"]*"?\S*|\S+/g) ?? [])
    .filter((token) => token.includes(":"))
    .sort((a, b) => b.length - a.length);
  return (
    tokens.find((token) => message.includes(token)) ??
    message.match(/['"„`]([^'"“`]+)['"“`]/)?.[1] ??
    message
  );
}
