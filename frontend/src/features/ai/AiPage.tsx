import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { useAiStatus, useCheckAiService, useEnqueueAi } from "../../api/queries";
import type {
  AiServiceInfo,
  AiStatus,
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
  queuedText,
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

/** The page "KI" (D180 to D189): what the text recognition does, the services, the work lists,
 *  the run, the queue, the results and what went out to the internet. */
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
        schlechte Scans. Der erkannte Text wird durchsuchbar wie jeder andere und überall als
        „maschinell erkannt“ gekennzeichnet; er kann Lesefehler enthalten und lässt sich jederzeit
        verwerfen.
      </p>
      <p>
        Die KI bewertet nichts und fasst nichts zusammen, sie liest nur Schrift. Sie arbeitet lokal:
        Dienste im Internet sind gesperrt, solange die .env sie nicht erlaubt. Gelesen wird nur, was
        hier oder in der Anhangsliste vorgemerkt ist, nie das ganze Archiv.
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
        {status.services.map((service) => (
          <ServiceRow key={service.capability} service={service} />
        ))}
      </ul>
      {status.services.length === 0 && (
        <p className={styles.muted}>
          Kein Bildmodell eingerichtet. Ohne eines liest Tesseract alles. Ein Bildmodell auf diesem
          Rechner (LM Studio oder Ollama) wird in der .env mit MAILROBBE_AI_VISION_URL und
          MAILROBBE_AI_VISION_MODEL eingetragen, etwa http://host.docker.internal:11434.
        </p>
      )}
    </Card>
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
            ? "Gesperrt: Dieser Dienst liegt außerhalb dieses Rechners und seines Netzes. Seitenbilder gingen damit ins Internet; erlaubt wird das nur in der .env mit MAILROBBE_AI_ALLOW_REMOTE=true."
            : "Gesperrt: Diese Adresse kann kein Dienst sein."}{" "}
          <span className={styles.technical}>{service.refused}</span>
        </p>
      )}
      {check.isPending && (
        <p className={styles.muted}>
          Der Dienst wird gefragt und liest ein Testbild; das kann beim ersten Laden des Modells
          eine Weile dauern.
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
        Was noch ohne erkannten Text ist. „Vormerken“ legt die Dokumente in die Warteschlange; der
        Lauf unten liest sie, die von vielen Mails getragenen zuerst.
      </p>
      <div className={styles.lists}>
        {status.work_lists.map((list) => (
          <WorkList key={list.key} list={list} vision={status.vision} />
        ))}
      </div>
    </Card>
  );
}

function WorkList({ list, vision }: { list: AiWorkListInfo; vision: boolean }) {
  const id = useId();
  const [engine, setEngine] = useState<OcrEngineChoice>("auto");
  const [notice, setNotice] = useState<string | null>(null);
  const enqueue = useEnqueueAi();
  const chosen = vision ? engine : "tesseract";
  const estimate = estimateFor(list.estimates, chosen, list.engine);
  const documents = `${formatNumber(list.documents)} ${list.documents === 1 ? "Dokument" : "Dokumente"}`;
  const pages =
    list.key === "scanned"
      ? ` · ${formatNumber(list.pages)} Seiten${list.without_pages > 0 ? ` (bei ${formatNumber(list.without_pages)} unbekannt)` : ""}`
      : "";

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
          <EngineSelect id={`${id}-engine`} value={chosen} vision={vision} onChange={setEngine} />
          <Button
            size="sm"
            disabled={enqueue.isPending}
            onClick={() =>
              enqueue.mutate(
                { work_list: list.key, engine: chosen },
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
