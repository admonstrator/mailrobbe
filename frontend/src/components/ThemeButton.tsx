import { setTheme, THEME_ORDER, useTheme, type ThemeChoice } from "../lib/theme";
import styles from "./HistoryMenu.module.css";
import { MonitorIcon, MoonIcon, SunIcon } from "./icons";

const LABELS: Record<ThemeChoice, string> = {
  system: "Darstellung wie das System",
  light: "Helle Darstellung",
  dark: "Dunkle Darstellung",
};

/** The header's button of light and dark (D339): each click goes on to the next of System,
 *  Hell and Dunkel; the icon shows the current choice. */
export function ThemeButton() {
  const theme = useTheme();
  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  const Icon = theme === "dark" ? MoonIcon : theme === "light" ? SunIcon : MonitorIcon;
  return (
    <button
      type="button"
      className={styles.button}
      aria-label={`${LABELS[theme]}, ändern`}
      title={`${LABELS[theme]}. Klick: ${LABELS[next]}`}
      onClick={() => setTheme(next)}
    >
      <Icon size={20} strokeWidth={1.8} />
    </button>
  );
}
