// The small icons of a profile's facts (D336), kept here: only the profile draws them.

import type { ReactNode } from "react";

function FactIcon({ children }: { children: ReactNode }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function DomainIcon() {
  return (
    <FactIcon>
      <path d="M4 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16M16 9h2a2 2 0 0 1 2 2v10M2 21h20M8 7h4M8 11h4M8 15h4" />
    </FactIcon>
  );
}

export function AddressIcon() {
  return (
    <FactIcon>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </FactIcon>
  );
}

export function NamesIcon() {
  return (
    <FactIcon>
      <path d="M7 7h10M7 12h7M5 20l3-3h11a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v13z" />
    </FactIcon>
  );
}

export function ActiveIcon() {
  return (
    <FactIcon>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18M8 3v4M16 3v4" />
    </FactIcon>
  );
}

export function ShieldIcon() {
  return (
    <FactIcon>
      <path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z" />
      <path d="m9 12 2 2 4-4" />
    </FactIcon>
  );
}
