import { Link } from "react-router";

import type { PersonRef } from "../api/types";
import { personName } from "../lib/person";

export function personPath(personId: number): string {
  return `/personen/${personId}`;
}

/** A person's name (or address) linking to their profile. */
export function PersonLink({ person, className }: { person: PersonRef; className?: string }) {
  return (
    <Link to={personPath(person.person_id)} className={className}>
      {personName(person)}
    </Link>
  );
}
