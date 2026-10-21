import { useEffect, useRef, type ComponentProps } from "react";

const DELAY = 300;

/** A text field whose value counts once typing pauses, as the person search does; a value that
 *  changes from outside (back, a link, a reset) replaces what it shows. */
export function DebouncedInput({
  value,
  onCommit,
  ...rest
}: Omit<ComponentProps<"input">, "value" | "defaultValue" | "onChange" | "ref"> & {
  value: string;
  onCommit: (value: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (input.current && input.current.value.trim() !== value) input.current.value = value;
  }, [value]);
  useEffect(() => () => clearTimeout(timer.current), []);

  return (
    <input
      ref={input}
      defaultValue={value}
      autoComplete="off"
      spellCheck={false}
      onChange={(event) => {
        const next = event.target.value.trim();
        clearTimeout(timer.current);
        timer.current = setTimeout(() => onCommit(next), DELAY);
      }}
      {...rest}
    />
  );
}
