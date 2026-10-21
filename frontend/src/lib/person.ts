// The name a person is shown by (D157): the name the team gave the address, else the name the
// mails use, else the address.

import type { AccountLabel } from "../api/types";

export interface Named {
  name: string | null;
  email: string;
  label?: AccountLabel | null;
}

export function personName(person: Named): string {
  return person.label?.name || person.name || person.email;
}
