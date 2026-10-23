import { Link } from "react-router";

import type { ImportOptions } from "../../api/types";
import { settingsValues, type SettingsDraft } from "./model";
import styles from "./SettingsCard.module.css";

/** The options of the next start from the dashboard (D49), prefilled with the settings (D315).
 *  A field keeps what the user typed while the status is polled; the others follow them. */
export function SettingsCard({
  defaults,
  draft,
  onChange,
}: {
  defaults: ImportOptions;
  draft: SettingsDraft;
  onChange: (draft: SettingsDraft) => void;
}) {
  const values = settingsValues(defaults, draft);
  return (
    <section className={styles.card} aria-labelledby="import-settings-title">
      <h2 id="import-settings-title" className={styles.title}>
        Nächster Start
      </h2>
      <div className={styles.grid}>
        <label htmlFor="import-workers">Parallele Worker</label>
        <input
          id="import-workers"
          type="number"
          min={1}
          max={64}
          step={1}
          className={styles.short}
          value={values.workers}
          onChange={(event) => onChange({ ...draft, workers: event.target.value })}
        />
        <label htmlFor="import-hash-limit">Anhang-Limit für Hash</label>
        <span className={styles.unit}>
          <input
            id="import-hash-limit"
            type="number"
            min={0}
            step={1}
            className={styles.short}
            value={values.hashLimitMb}
            onChange={(event) => onChange({ ...draft, hashLimitMb: event.target.value })}
          />
          MB
        </span>
        <label htmlFor="import-dns">DNS-Resolver</label>
        <input
          id="import-dns"
          type="text"
          placeholder="System-Resolver"
          autoComplete="off"
          spellCheck={false}
          className={styles.dns}
          value={values.nameservers}
          onChange={(event) => onChange({ ...draft, nameservers: event.target.value })}
        />
      </div>
      <p className={styles.fixed}>Volltext: immer an (Betreff und Textteil)</p>
      <p className={styles.hint}>
        Gilt nur für den nächsten Start aus dem Dashboard; dauerhaft unter{" "}
        <Link to="/einstellungen">Einstellungen</Link>.
      </p>
    </section>
  );
}
