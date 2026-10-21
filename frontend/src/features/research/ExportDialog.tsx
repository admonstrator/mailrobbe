import type { MailSelection } from "../../api/types";

export interface ExportDialogProps {
  /** The mails to export: the list's filters, selected ids, or an Akte as filter. */
  selection: MailSelection;
  /** How many mails the selection has, when the caller knows it; null: unknown. */
  count: number | null;
  /** Suggested label for the export log, e.g. the Akte's name. */
  label: string;
  onClose: () => void;
}

/** Export of mails as ZIP with EML, PDF and manifest (D62). Placeholder of the contract; the
 *  Akten agent builds it, the mail list opens it. */
export function ExportDialog(props: ExportDialogProps) {
  void props;
  return null;
}
