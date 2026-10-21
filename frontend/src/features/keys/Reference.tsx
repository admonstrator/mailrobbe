import { Link } from "react-router";

const INTERNAL = /^\/(m|mails|anhaenge)\/[0-9A-Za-z]+$/;

/** Where a piece of evidence comes from: a web address opens in a new tab, a permalink /m/…,
 *  a mail or a document page of this archive inside the app, anything else (a file name, a
 *  description) stays text. */
export function Reference({ value }: { value: string }) {
  if (/^https?:\/\/\S+$/i.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer noopener">
        {value}
      </a>
    );
  }
  if (INTERNAL.test(value)) return <Link to={value}>{value}</Link>;
  return <span>{value}</span>;
}
