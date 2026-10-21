import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError, withQuery } from "../../api/client";
import { usePerson } from "../../api/queries";
import type { PersonProfile } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { MiniTimeline } from "../timeline/MiniTimeline";
import { PersonTermsCard } from "../topics/PersonTermsCard";
import { personLabel } from "./labels";
import { MergeDialog } from "./MergeDialog";
import { PersonEventsCard } from "./PersonEventsCard";
import { PersonMails } from "./PersonMails";
import styles from "./PersonProfilePage.module.css";
import { PersonSignalsCard } from "./PersonSignalsCard";
import { ProfileHeader } from "./ProfileHeader";
import { ProfileTiles } from "./ProfileTiles";
import { TopContacts } from "./TopContacts";
import {
  parseProfileMailState,
  profileMailSearch,
  withSelection,
  type ProfileMailState,
} from "./urlState";
import { YearChart } from "./YearChart";

/** The person profile (SPEC 5.3, mockup "3 · Personenprofil"). An alias's URL is replaced by
 *  its root's, so every address of a person shows the same page. */
export function PersonProfilePage() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <div className={styles.page}>
        <PersonNotFound />
      </div>
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
    <div className={styles.page}>
      <title>{`${name ?? "Person"} · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/personen">Personen</Link>
        {name && (
          <>
            <span aria-hidden="true">›</span>
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
          <Card className={styles.message}>
            <ErrorState
              title="Das Profil konnte nicht geladen werden."
              actions={<Button onClick={() => void profile.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </Card>
        )
      ) : (
        <Profile profile={profile.data} />
      )}
    </div>
  );
}

function Profile({ profile }: { profile: PersonProfile }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseProfileMailState(searchParams), [searchParams]);
  const [merging, setMerging] = useState(false);
  const navigate = useNavigate();
  // The person's mails as the profile's tabs count them (D32), by month.
  const mails = { person: [profile.id], hide_duplicates: true };
  const setState = (next: ProfileMailState) =>
    setSearchParams(profileMailSearch(next), { preventScrollReset: true });
  const href = (next: ProfileMailState) => {
    const search = profileMailSearch(next).toString();
    return `${personPath(profile.id)}${search ? `?${search}` : ""}`;
  };

  return (
    <div className={styles.content}>
      <ProfileHeader profile={profile} onMerge={() => setMerging(true)} />
      {profile.figures ? (
        <ProfileTiles figures={profile.figures} />
      ) : (
        <Card className={styles.pending}>
          Die Kennzahlen dieser Person werden beim nächsten Import berechnet.
        </Card>
      )}
      <div className={styles.charts}>
        <TopContacts profile={profile} />
        <YearChart
          years={profile.years}
          selected={state.year}
          onSelect={(year) => setState(withSelection(state, { year }))}
        />
      </div>
      {profile.figures?.sent !== 0 && <PersonTermsCard personId={profile.id} />}
      <MiniTimeline
        filters={mails}
        bucket="month"
        onPick={(range) => void navigate(withQuery("/mails", { ...mails, ...range }))}
        silenceLine
      />
      <PersonSignalsCard personId={profile.id} />
      <PersonEventsCard personId={profile.id} />
      <PersonMails profile={profile} state={state} onChange={setState} href={href} />
      {merging && <MergeDialog profile={profile} onClose={() => setMerging(false)} />}
    </div>
  );
}

function PersonNotFound({ id }: { id?: number }) {
  return (
    <Card className={styles.message}>
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
    </Card>
  );
}
