import { ApiError } from "../../api/client";

/** What the UI says about a preview that could not be loaded. */
export interface PreviewProblem {
  title: string;
  text?: string;
  /** The server's technical reason, shown as a muted line. */
  reason?: string;
  /** Whether asking again can help. */
  retry: boolean;
}

/** German text for a failed read or conversion of an attachment for its preview (D76, D120). */
export function previewProblem(error: Error): PreviewProblem {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "source_missing":
        return { title: "Die MBOX-Datei ist nicht erreichbar.", retry: true };
      case "source_changed":
        return {
          title:
            "Die MBOX-Datei hat sich seit dem Import geändert; an dieser Stelle steht nicht mehr dieser Anhang.",
          retry: false,
        };
      case "not_found":
        return { title: "Diesen Anhang gibt es nicht mehr.", retry: false };
      case "no_preview":
        return {
          title: "Für diese Datei gibt es keine Vorschau im Browser. Herunterladen geht trotzdem.",
          reason: error.message,
          retry: false,
        };
      case "preview_too_large":
        return {
          title: "Die Datei ist zu groß für eine Vorschau. Herunterladen geht trotzdem.",
          retry: false,
        };
      case "preview_failed":
        return {
          title: "Die Vorschau ließ sich nicht erstellen. Herunterladen geht trotzdem.",
          reason: error.message,
          retry: true,
        };
    }
  }
  return {
    title: "Die Vorschau konnte nicht geladen werden.",
    text: "Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.",
    retry: true,
  };
}
