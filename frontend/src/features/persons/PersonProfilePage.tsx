import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { usePerson, usePersonEvents, usePersonSignals } from "../../api/queries";
import type { PersonProfile } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import { GraphIcon } from "../../components/icons";
import { OverflowMenu } from "../../components/OverflowMenu";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatNumber } from "../../lib/format";
import { useRecordVisit } from "../../lib/history";
import { timelinePath } from "../timeline/buckets";
import { personLabel } from "./labels";
import { MergeDialog } from "./MergeDialog";
import { PersonEventsCard, personEventsHref } from "./PersonEventsCard";
import { PersonMails } from "./PersonMails";
import styles from "./PersonProfilePage.module.css";
import { PersonSignalsCard } from "./PersonSignalsCard";
import { ProfileAside } from "./ProfileAside";
import { ProfileContacts } from "./ProfileContacts";
import { personDocumentsHref, ProfileDocuments } from "./ProfileDocuments";
import { ProfileOverview } from "./ProfileOverview";
import {
  parseProfileMailState,
  parseProfileTab,
  profileSearch,
  withSelection,
  type ProfileMailState,
  type ProfileTab,
} from "./urlState";

const TABS_ID = "profile";

const TAB_LABELS: Record<ProfileTab, string> = {
  ueberblick: "Überblick",
  mails: "Mails",
  kontakte: "Kontakte",
  anhaenge: "Anhänge",
  termine: "Termine",
  signale: "Signale",
};

/** Starts the download of url, as a link with download does. */
function download(url: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

/** The person profile (SPEC 5.3, D336): a column of who it is at the left, tabs at the right. An
 *  alias's URL is replaced by its root's, so every address of a person shows the same page. */
export function PersonProfilePage() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <main className={styles.page}>
        <PersonNotFound />
      </main>
    );
  }
  return <ProfileView key={id} id={Number(id)} />;
}

function ProfileView({ id }: { id: number }) {
  const profile = usePerson(id);
  const navigate = useNavigate();
  const location = useLocation();
  const rootId = profile.data?.id;

  useEffect(() => {
    if (rootId !== undefined && rootId !== id) {
      void navigate({ pathname: personPath(rootId), search: location.search }, { replace: true });
    }
  }, [rootId, id, location.search, navigate]);

  const name = profile.data ? personLabel(profile.data) : null;
  return (
    <main className={styles.page}>
      <title>{`${name ?? "Person"} · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/personen">Personen</Link>
        {name && (
          <>
            <span aria-hidden="true">/</span>
            <span>{name}</span>
          </>
        )}
      </nav>
      {profile.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Profil wird geladen" />
        </div>
      ) : profile.isError ? (
        profile.error instanceof ApiError && profile.error.code === "not_found" ? (
          <PersonNotFound id={id} />
        ) : (
          <ErrorState
            title="Das Profil konnte nicht geladen werden."
            actions={<Button onClick={() => void profile.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        )
      ) : (
        <Profile profile={profile.data} />
      )}
    </main>
  );
}

function Profile({ profile }: { profile: PersonProfile }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseProfileMailState(searchParams), [searchParams]);
  const tab = useMemo(() => parseProfileTab(searchParams), [searchParams]);
  const [merging, setMerging] = useState(false);
  const navigate = useNavigate();
  const events = usePersonEvents(profile.id);
  const signals = usePersonSignals(profile.id);

  useRecordVisit({
    kind: "person",
    id: profile.id,
    title: personLabel(profile),
    subtitle: profile.email,
    path: personPath(profile.id),
  });

  const searchOf = (next: ProfileTab, mails: ProfileMailState) => {
    const search = profileSearch(next, mails).toString();
    return `${personPath(profile.id)}${search ? `?${search}` : ""}`;
  };
  const setTab = (next: ProfileTab) =>
    next !== tab && setSearchParams(profileSearch(next, state), { preventScrollReset: true });
  const setState = (next: ProfileMailState) =>
    setSearchParams(profileSearch("mails", next), { preventScrollReset: true });

  const exportQuery = new URLSearchParams({
    person: String(profile.id),
    hide_duplicates: "true",
  });
  const counts: Partial<Record<ProfileTab, number | undefined>> = {
    mails: profile.figures?.mails,
    kontakte: profile.figures?.contacts,
    termine: events.data?.total,
    signale: signals.data?.signals.length,
  };
  const tabs: TabItem<ProfileTab>[] = (Object.keys(TAB_LABELS) as ProfileTab[]).map((id) => {
    const count = counts[id];
    return {
      id,
      label: count === undefined ? TAB_LABELS[id] : `${TAB_LABELS[id]} ${formatNumber(count)}`,
    };
  });

  const actions = (
    <div className={styles.actions}>
      <Link to={`/karte?center=${profile.id}`} className={buttonClass()}>
        <GraphIcon size={14} />
        Im Graphen zeigen
      </Link>
      <OverflowMenu
        items={[
          {
            label: "Alle Mails exportieren",
            onSelect: () => download(`/api/mails/export.csv?${exportQuery}`),
          },
          {
            label: "Anhänge dieser Person",
            onSelect: () => void navigate(personDocumentsHref(profile.id)),
          },
          {
            label: "Einladungen in der Mailliste",
            onSelect: () => void navigate(personEventsHref(profile.id)),
          },
          {
            label: "In der Zeitachse öffnen",
            onSelect: () => void navigate(timelinePath({ person: [profile.id] })),
          },
          {
            label: "Adresse zusammenführen …",
            onSelect: () => setMerging(true),
            separated: true,
          },
        ]}
      />
    </div>
  );

  return (
    <div className={styles.layout}>
      <ProfileAside
        profile={profile}
        onContacts={() => setTab("kontakte")}
        onMerge={() => setMerging(true)}
      />
      <div className={styles.main}>
        <div className={styles.tabs}>
          <Tabs<ProfileTab>
            items={tabs}
            active={tab}
            onSelect={setTab}
            idPrefix={TABS_ID}
            label="Bereiche des Profils"
            end={actions}
          />
        </div>
        <div {...tabPanelProps(TABS_ID, tab)} className={styles.panel}>
          {tab === "ueberblick" && <ProfileOverview profile={profile} onTab={setTab} />}
          {tab === "mails" && (
            <PersonMails
              profile={profile}
              state={state}
              onChange={setState}
              href={(next) => searchOf("mails", next)}
            />
          )}
          {tab === "kontakte" && (
            <ProfileContacts
              profile={profile}
              mailsHref={(contact) => searchOf("mails", withSelection(state, { contact }))}
            />
          )}
          {tab === "anhaenge" && <ProfileDocuments personId={profile.id} />}
          {tab === "termine" && (
            <EventsTab personId={profile.id} empty={events.data?.total === 0} />
          )}
          {tab === "signale" && <SignalsTab personId={profile.id} />}
        </div>
      </div>
      {merging && <MergeDialog profile={profile} onClose={() => setMerging(false)} />}
    </div>
  );
}

function EventsTab({ personId, empty }: { personId: number; empty: boolean }) {
  if (empty) {
    return (
      <p className={styles.empty}>
        Diese Person hat keine Einladung verschickt oder bekommen.{" "}
        <Link to={personEventsHref(personId)}>Einladungen in der Mailliste</Link>
      </p>
    );
  }
  return <PersonEventsCard personId={personId} />;
}

function SignalsTab({ personId }: { personId: number }) {
  const signals = usePersonSignals(personId);
  const none =
    signals.data && signals.data.signals.length === 0 && signals.data.silent_since === null;
  if (none) {
    return (
      <p className={styles.empty}>
        Keine gesendete Mail dieser Person trägt ein Signal.{" "}
        <Link to="/signale">Zu den Signalen</Link>
      </p>
    );
  }
  return <PersonSignalsCard personId={personId} />;
}

function PersonNotFound({ id }: { id?: number }) {
  return (
    <ErrorState
      title="Diese Person gibt es nicht."
      actions={
        <Link to="/personen" className={buttonClass()}>
          Zur Personenliste
        </Link>
      }
    >
      {id === undefined
        ? "Die Adresse nennt keine gültige Personen-Nummer."
        : `Im Archiv gibt es keine Person mit der Nummer #${id}.`}
    </ErrorState>
  );
}
