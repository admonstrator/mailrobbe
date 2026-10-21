import type { ReactNode } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../persons/Dialog";
import forms from "./forms.module.css";
import { researchErrorText } from "./labels";

/** Asks before something is deleted: what goes and what stays, then the action. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
  pending,
  error,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
  pending: boolean;
  error: Error | null;
}) {
  return (
    <Dialog title={title} onClose={onClose}>
      <div className={forms.form}>
        <p className={forms.text}>{children}</p>
        {error && (
          <p className={forms.error} role="alert">
            {researchErrorText(error)}
          </p>
        )}
        <div className={forms.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button variant="primary" onClick={onConfirm} disabled={pending}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
