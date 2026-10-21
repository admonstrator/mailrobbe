import { ApiError } from "../../api/client";

/** German text for a failed read of the mail's source (D22), else a general one. */
export function sourceErrorText(error: Error): string {
  if (error instanceof ApiError) {
    if (error.code === "source_missing") return "Die MBOX-Datei ist nicht erreichbar.";
    if (error.code === "source_changed") {
      return "Die Datei hat sich seit dem Import geändert; an dieser Stelle steht nicht mehr diese Mail.";
    }
  }
  return "Die Mail konnte nicht aus der MBOX-Datei gelesen werden.";
}
