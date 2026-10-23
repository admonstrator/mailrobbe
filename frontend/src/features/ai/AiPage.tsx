import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router";

import { useAiStatus, useCheckAiService, useEnqueueAi } from "../../api/queries";
import type {
  AiServiceInfo,
  AiStatus,
  AiTranscriptionInfo,
  AiWorkListInfo,
  OcrEngineChoice,
  ServiceCheck,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatBytes, formatNumber } from "../../lib/format";
import { AiRunCard } from "./AiRunCard";
import { QueueCard, ResultsCard, SentCard } from "./AiLists";
import styles from "./AiPage.module.css";
import { EngineSelect } from "./EngineSelect";
import {
  aiErrorText,
  estimateFor,
  estimateText,
  minutesText,
  queuedText,
  transcriberName,
  WORK_LIST_HINTS,
  WORK_LIST_TITLES,
} from "./labels";

/** When a run ends, its texts reach every screen: everything is loaded again. */
function useRefreshWhenRunEnds(alive: boolean) {
  const queryClient = useQueryClient();
  const before = useRef(alive);
  useEffect(() => {
    if (before.current && !alive) void queryClient.invalidateQueries();
    before.current = alive;
  }, [alive, queryClient]);
}

/** The page "KI" (D180 to D189, D295): what the text recognition and the transcription do, the
 *  services and the transcriber, the work lists, the run, the queue, the results and what went
 *  out to the internet. */
export function AiPage() {
  const status = useAiStatus();
  useRefreshWhenRunEnds(Boolean(status.data?.job?.alive));

  return (
    <main className={styles.page}>
      <title>KI · Mailrobbe</title>
      <h1 className={styles.title}>KI</h1>
      <Intro />
      {status.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="KI-Status wird geladen" />
        </Card>
      ) : status.isError ? (
        <Card>
          <ErrorState
            title="Der KI-Status konnte nicht geladen werden."
            actions={<Button onClick={() => void status.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <Content status={status.data} />
      )}
    </main>
  );
}

function Intro() {
  return (
    <Card className={styles.intro} aria-label="Was die KI macht">
      <p>
        Gescannte PDFs und Bilder haben keine Textebene, die Volltextsuche findet sie nur über den
        Dateinamen. Die Texterkennung liest ihre Schrift: Tesseract im Container für die Masse, ein
        Bildmodell auf diesem Rechner (etwa in LM Studio oder Ollama) für Handschrift, Fotos und
        schlechte Scans. Sprachnachrichten und Videos schreibt die Transkription mit, ebenfalls im
        Container, mit der Zeit jeder Zeile. Erkannter Text und Transkripte werden durchsuchbar wie
        jeder andere Text und überall als „maschinell erkannt“ oder „maschinell transkribiert“
        gekennzeichnet; sie können Lese- und Hörfehler enthalten und lassen sich jederzeit
        verwerfen.
      </p>
      <p>
        Ein Textmodell fasst auf Wunsch einzelne Mails und Dokumente oder eine Auswahl zusammen und
        vergibt Schlagwörter und Hinweise auf Themen. Zusammenfassungen sind überall als „maschinell
        erzeugt“ gekennzeichnet, mit Modell und Datum; sie werden nicht durchsuchbar, ihre
        Schlagwörter filtern nur die Mailliste. Jede lässt sich verwerfen.
      </p>
      <p>
        Die KI bewertet nichts. Sie arbeitet lokal: Dienste im Internet sind gesperrt, solange die
        .env sie nicht erlaubt. Gelesen wird nur, was hier, in der Anhangsliste, in der Mailliste
        oder auf der Seite einer Mail oder eines Dokuments vorgemerkt ist, nie das ganze Archiv.
      </p>
    </Card>
  );
}

function Content({ status }: { status: AiStatus }) {
  const alive = Boolean(status.job?.alive);
  return (
    <>
      <ServicesCard status={status} />
      <WorkListsCard status={status} />
      <AiRunCard status={status} />
      <QueueCard status={status} alive={alive} />
      <ResultsCard alive={alive} />
      {status.remote_used && <SentCard />}
    </>
  );
}

// Services --------------------------------------------------------------------------------------

const CAPABILITY_LABELS: Record<AiServiceInfo["capability"], string> = {
  vision: "Bildmodell (Bilder und Seiten lesen)",
  text: "Textmodell (zusammenfassen und verschlagworten)",
};

/** What a service's check does, and what would leave the machine with a remote one. */
const TEST_LABELS: Record<AiServiceInfo["capability"], string> = {
  vision: "liest ein Testbild",
  text: "bekommt einen kurzen Testtext",
};

const SENT_LABELS: Record<AiServiceInfo["capability"], string> = {
  vision: "Seitenbilder",
  text: "Texte von Mails und Dokumenten",
};

function ServicesCard({ status }: { status: AiStatus }) {
  return (
    <Card aria-labelledby="ai-services-title">
      <CardTitle id="ai-services-title">Dienste</CardTitle>
      <ul className={styles.services}>
        <li className={styles.service}>
          <div className={styles.serviceHead}>
            <strong>Tesseract</strong>
            <span className={cx(styles.place, styles.local)}>im Container</span>
          </div>
          <span className={styles.muted}>
            {status.tesseract
              ? `Texterkennung für Scans, Sprachen ${status.ocr_languages}; braucht keinen weiteren Dienst.`
              : "Tesseract ist dort, wo der Server läuft, nicht installiert; im Docker-Image ist es enthalten."}
          </span>
        </li>
        {status.transcription && <TranscriberRow transcriber={status.transcription} />}
        {status.services.map((service) => (
          <ServiceRow key={service.capability} service={service} />
        ))}
      </ul>
      {!status.services.some((service) => service.capability === "vision") && (
        <p className={styles.muted}>
          Kein Bildmodell eingerichtet. Ohne eines liest Tesseract alles. Ein Bildmodell auf diesem
          Rechner (LM Studio oder Ollama) wird unter <Link to="/einstellungen">Einstellungen</Link>{" "}
          mit Adresse und Modell eingetragen, etwa http://host.docker.internal:11434.
        </p>
      )}
      {!status.services.some((service) => service.capability === "text") && (
        <p className={styles.muted}>
          Kein Textmodell eingerichtet, also keine Zusammenfassungen und Schlagwörter. Ein
          Textmodell auf diesem Rechner wird unter <Link to="/einstellungen">Einstellungen</Link>{" "}
          mit Adresse und Modell eingetragen, etwa http://host.docker.internal:1234/v1.
        </p>
      )}
    </Card>
  );
}

/** The transcriber in the container (D290, D291): its model, the threads, the limit per
 *  recording, and whether its files are there or come with the first run. */
function TranscriberRow({ transcriber }: { transcriber: AiTranscriptionInfo }) {
  const { missing_bytes: missing, total_bytes: total } = transcriber;
  return (
    <li className={styles.service}>
      <div className={styles.serviceHead}>
        <strong>{transcriberName(transcriber.model, true)}</strong>
        <span className={cx(styles.place, styles.local)}>im Container</span>
      </div>
      {transcriber.available ? (
        <>
          <span className={styles.muted}>
            {`Transkription von Sprachnachrichten und Videos, auf dem Prozessor (CPU) mit ${formatNumber(transcriber.threads)} ${transcriber.threads === 1 ? "Thread" : "Threads"}; höchstens ${formatNumber(transcriber.max_minutes)} Minuten je Aufnahme. Braucht keinen weiteren Dienst.`}
          </span>
          <span className={styles.muted}>
            {transcriber.ready
              ? `Modelldateien vorhanden (${formatBytes(total)}).`
              : missing < total
                ? `Modelldateien werden beim ersten Lauf zu Ende geladen (noch ${formatBytes(missing)} von ${formatBytes(total)}).`
                : `Modelldateien werden beim ersten Lauf geladen (${formatBytes(missing)}).`}
            {!transcriber.ready &&
              " Aus dem Archiv geht dabei nichts hinaus; ohne Netz lassen sie sich von Hand nach MAILROBBE_AI_MODEL_DIR kopieren."}
          </span>
        </>
      ) : (
        <span className={styles.muted}>
          Die Bibliotheken der Transkription (onnx-asr, ONNX Runtime, PyAV) fehlen dort, wo der
          Server läuft; im Docker-Image sind sie enthalten.
        </span>
      )}
    </li>
  );
}

function ServiceRow({ service }: { service: AiServiceInfo }) {
  const check = useCheckAiService();
  const remote = service.locality === "remote";
  return (
    <li className={styles.service}>
      <div className={styles.serviceHead}>
        <strong>{CAPABILITY_LABELS[service.capability]}</strong>
        {service.locality && (
          <span className={cx(styles.place, remote ? styles.remote : styles.local)}>
            {remote ? "Internet" : "lokal"}
          </span>
        )}
        <Button
          size="sm"
          className={styles.serviceAction}
          disabled={check.isPending || service.refused !== null}
          onClick={() => check.mutate(service.capability)}
        >
          {check.isPending ? "Wird getestet …" : "Testen"}
        </Button>
      </div>
      <dl className={styles.facts}>
        <dt>Adresse</dt>
        <dd className={styles.mono}>{service.url}</dd>
        <dt>Modell</dt>
        <dd className={styles.mono}>{service.model || "nicht eingetragen"}</dd>
        <dt>Protokoll</dt>
        <dd>{service.protocol === "auto" ? "wird erkannt" : service.protocol}</dd>
      </dl>
      {service.refused !== null && (
        <p className={styles.warning}>
          {service.locality === "remote"
            ? `Gesperrt: Dieser Dienst liegt außerhalb dieses Rechners und seines Netzes. ${SENT_LABELS[service.capability]} gingen damit ins Internet; erlaubt wird das nur in der .env mit MAILROBBE_AI_ALLOW_REMOTE=true.`
            : "Gesperrt: Diese Adresse kann kein Dienst sein."}{" "}
          <span className={styles.technical}>{service.refused}</span>
        </p>
      )}
      {check.isPending && (
        <p className={styles.muted}>
          {`Der Dienst wird gefragt und ${TEST_LABELS[service.capability]}; das kann beim ersten Laden des Modells eine Weile dauern.`}
        </p>
      )}
      {check.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(check.error)}
        </p>
      )}
      {check.data && <CheckResult check={check.data} />}
    </li>
  );
}

/** What the check found: reachable, models, the real test with what came back (D180). */
function CheckResult({ check }: { check: ServiceCheck }) {
  const passed = check.test === "passed";
  const models = check.models.map((model) => model.name);
  return (
    <div className={styles.check} role="status">
      <span>
        {check.reachable
          ? `Erreichbar${check.protocol ? ` (${check.protocol === "ollama" ? "Ollama" : "OpenAI-kompatibel"})` : ""}`
          : check.refused
            ? "Nicht gefragt: Der Dienst ist gesperrt."
            : "Nicht erreichbar."}
      </span>
      {models.length > 0 && (
        <span>
          {`Modelle: ${models.slice(0, 8).join(", ")}${models.length > 8 ? ` und ${formatNumber(models.length - 8)} weitere` : ""}`}
        </span>
      )}
      {check.model_found === false && (
        <span className={styles.warningText}>
          {`Das eingetragene Modell „${check.model}“ bietet der Dienst nicht an.`}
        </span>
      )}
      {check.test && (
        <span className={passed ? styles.passed : styles.failed}>
          {passed ? "Test bestanden" : "Test nicht bestanden"}
          {check.seconds !== null && ` · ${check.seconds.toLocaleString("de-DE")} s`}
        </span>
      )}
      {check.test_detail && (
        <span className={styles.technical}>{`Antwort: ${check.test_detail}`}</span>
      )}
      {check.error && <span className={styles.technical}>{check.error}</span>}
    </div>
  );
}

// Work lists ------------------------------------------------------------------------------------

function WorkListsCard({ status }: { status: AiStatus }) {
  return (
    <Card aria-labelledby="ai-lists-title">
      <CardTitle id="ai-lists-title">Arbeitslisten</CardTitle>
      <p className={styles.muted}>
        Was noch ohne erkannten Text oder Transkript ist. „Vormerken“ legt die Dokumente in die
        Warteschlange; der Lauf unten liest sie, die von vielen Mails getragenen zuerst.
      </p>
      <div className={styles.lists}>
        {status.work_lists.map((list) => (
          <WorkList
            key={list.key}
            list={list}
            vision={status.vision}
            transcriber={status.transcription}
          />
        ))}
      </div>
    </Card>
  );
}

/** A work list (D186): what it holds, how long it takes, "Vormerken". Recordings (D295) count
 *  their known minutes and those of unknown length, and have one engine, so no select. */
function WorkList({
  list,
  vision,
  transcriber,
}: {
  list: AiWorkListInfo;
  vision: boolean;
  transcriber: AiTranscriptionInfo | null | undefined;
}) {
  const id = useId();
  const [engine, setEngine] = useState<OcrEngineChoice>("auto");
  const [notice, setNotice] = useState<string | null>(null);
  const enqueue = useEnqueueAi();
  const media = list.key === "media";
  const chosen = vision ? engine : "tesseract";
  const estimate = estimateFor(list.estimates, media ? "auto" : chosen, list.engine);
  const documents = `${formatNumber(list.documents)} ${list.documents === 1 ? "Dokument" : "Dokumente"}`;
  const unknown = list.without_minutes ?? 0;
  const pages =
    list.key === "scanned"
      ? ` · ${formatNumber(list.pages)} Seiten${list.without_pages > 0 ? ` (bei ${formatNumber(list.without_pages)} unbekannt)` : ""}`
      : media
        ? ` · ${minutesText(list.minutes ?? 0)}${unknown > 0 ? ` (${formatNumber(unknown)} ohne bekannte Länge)` : ""}`
        : "";
  // Without its libraries the server transcribes nothing (D290).
  const missing = media && transcriber?.available === false;

  return (
    <section className={styles.list} aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`} className={styles.listTitle}>
        {WORK_LIST_TITLES[list.key]}
      </h3>
      <p className={styles.muted}>{WORK_LIST_HINTS[list.key]}</p>
      <p className={styles.figures}>
        <strong>{documents}</strong>
        {pages}
        {` · ${formatBytes(list.bytes)}`}
        {estimate && list.documents > 0 && ` · ${estimateText(estimate)}`}
      </p>
      {list.documents > 0 && (
        <div className={styles.listForm}>
          {media ? (
            <span className={styles.muted}>
              {missing
                ? "Ohne die Bibliotheken der Transkription lässt sich nichts vormerken."
                : `Verfahren: ${transcriberName(transcriber?.model ?? null)} im Container`}
            </span>
          ) : (
            <EngineSelect id={`${id}-engine`} value={chosen} vision={vision} onChange={setEngine} />
          )}
          <Button
            size="sm"
            disabled={enqueue.isPending || missing}
            onClick={() =>
              enqueue.mutate(
                media ? { work_list: list.key } : { work_list: list.key, engine: chosen },
                {
                  onSuccess: (queued) => setNotice(queuedText(queued)),
                  onError: (error) => setNotice(aiErrorText(error)),
                },
              )
            }
          >
            Vormerken
          </Button>
        </div>
      )}
      {notice && (
        <p className={styles.muted} role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
