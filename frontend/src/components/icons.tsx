// Small inline SVG icons. Decorative unless a label is given, which makes them an image.

import type { ReactNode } from "react";

interface IconProps {
  size?: number;
  label?: string;
  className?: string;
  strokeWidth?: number;
}

function Icon({
  size = 16,
  label,
  className,
  strokeWidth = 2,
  children,
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}
    >
      {label && <title>{label}</title>}
      {children}
    </svg>
  );
}

export function LogoIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
      <path
        d="M13 13L3 6M13 13L23 6M13 13L3 20M13 13L23 20M13 13V2M13 13V24"
        stroke="var(--color-accent)"
        strokeWidth="1.5"
      />
      <g fill="var(--color-accent)">
        <circle cx="13" cy="13" r="4" />
        <circle cx="3" cy="6" r="2" />
        <circle cx="23" cy="6" r="2" />
        <circle cx="3" cy="20" r="2" />
        <circle cx="23" cy="20" r="2" />
        <circle cx="13" cy="2" r="1.5" />
        <circle cx="13" cy="24" r="1.5" />
      </g>
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Icon>
  );
}

export function PaperclipIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M21 11.5l-8.5 8.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" />
    </Icon>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M20 6L9 17l-5-5" />
    </Icon>
  );
}

export function CrossIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M18 6L6 18M6 6l12 12" />
    </Icon>
  );
}

export function AlertIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5v.01" />
    </Icon>
  );
}

export function MinusIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M6 12h12" />
    </Icon>
  );
}

export function FileIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
    </Icon>
  );
}

export function GraphIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="5" cy="12" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="M7 11l10-4M7 13l10 4" />
    </Icon>
  );
}

export function FlagIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
    </Icon>
  );
}

export function CopyIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V6a2 2 0 0 1 2-2h9" />
    </Icon>
  );
}
