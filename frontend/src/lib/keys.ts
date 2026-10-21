/** True when a key press goes to a text field, select or editable element, so global shortcuts
 *  ("/", the arrow keys) must leave it alone. */
export function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/** A plain key press without Ctrl, Alt or Meta that nothing else handled. */
export function isPlainKey(event: KeyboardEvent): boolean {
  return (
    !event.defaultPrevented &&
    !event.ctrlKey &&
    !event.altKey &&
    !event.metaKey &&
    !isTypingTarget(event.target)
  );
}
