import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { usePhotoDetail, usePhotoList } from "../../api/queries";
import type {
  EventPlace,
  PhotoDetail,
  PhotoListItem,
  PlaceCounts,
  PlaceMail,
  PlaceParams,
  PlaceSummary,
  TextPlace,
} from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDate, formatNumber } from "../../lib/format";
import { openStreetMapUrl } from "../../lib/osm";
import { personName } from "../../lib/person";
import { documentMailsHref, documentPath } from "../documents/urlState";
import { entityPath } from "../entities/urlState";
import { EVENT_LABELS } from "../mails/chips";
import { ImagePreview } from "../preview/AttachmentPreview";
import { ImageViewer } from "../preview/ImageViewer";
import {
  coordinatesText,
  countText,
  eventStartText,
  formatKm,
  nearestText,
  placesStepNotice,
  regionText,
  takenText,
} from "./labels";
import styles from "./PointPanel.module.css";
import { textPlaceMailsHref, type MapView, type PlacesState, type PointRef } from "./urlState";

/** "Fotos im Umkreis" (D248): the radii offered, in km. */
export const RADII_KM = [0.5, 2, 10, 50] as const;
const DEFAULT_RADIUS_KM = 2;
/** Photos a list of the panel shows. */
export const PANEL_PHOTOS = 50;

const NO_SUBJECT = "(ohne Betreff)";

/** A point picked in a panel's list, and where the map brings it into view. */
export type Pick = (point: PointRef, at?: MapView) => void;

function Frame({
  kind,
  title,
  onClose,
  children,
}: {
  kind: string;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}) {
  return (
    <section className={styles.panel} aria-label={kind}>
      <div className={styles.head}>
        <div className={styles.heading}>
          <span className={styles.kind}>{kind}</span>
          <h2 className={styles.title}>{title}</h2>
        </div>
        <button type="button" className={styles.close} aria-label="Schließen" onClick={onClose}>
          ×
        </button>
      </div>
      {children}
    </section>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className={styles.loading}>
      <Spinner label={label} />
    </div>
  );
}

/** The mails carrying a photo: date, sender, recipients and subject, to the mail detail. */
function MailList({ mails }: { mails: PlaceMail[] }) {
  return (
    <ul className={styles.mails}>
      {mails.map((mail) => {
        const others = mail.recipient_count - mail.recipients.length;
        const recipients = mail.recipients.map(personName).join(", ");
        return (
          <li key={mail.id}>
            <Link to={`/mails/${mail.id}`} className={styles.mail}>
              <span className={styles.mailHead}>
                <span className={styles.mailDate}>
                  {mail.date ? formatDate(mail.date) : "ohne Datum"}
                </span>
                <span className={styles.mailPeople}>
                  {mail.sender ? personName(mail.sender) : "unbekannt"}
                  {(recipients || others > 0) && " → "}
                  {recipients}
                  {others > 0 && ` +${formatNumber(others)}`}
                </span>
              </span>
              <span className={styles.subject}>{mail.subject || NO_SUBJECT}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** A photo (D248): the picture, when and with what it was taken, where, its mails, and the
 *  photos around it and of its device. */
export function PhotoPanel({
  id,
  params,
  onPick,
  onClose,
}: {
  id: number;
  params: PlaceParams;
  onPick: Pick;
  onClose: () => void;
}) {
  const photo = usePhotoDetail(id);
  const [large, setLarge] = useState(false);

  if (photo.isPending) {
    return (
      <Frame kind="Foto" title="Foto" onClose={onClose}>
        <Loading label="Foto wird geladen" />
      </Frame>
    );
  }
  if (photo.isError) {
    const missing = photo.error instanceof ApiError && photo.error.status === 404;
    return (
      <Frame kind="Foto" title="Foto" onClose={onClose}>
        <p className={styles.note} role="alert">
          {missing
            ? "Dieses Foto gibt es nicht mehr oder es hat keine Position."
            : "Das Foto lässt sich gerade nicht laden."}
        </p>
      </Frame>
    );
  }

  const data = photo.data;
  const name = data.name || "(ohne Dateinamen)";
  return (
    <Frame kind="Foto" title={name} onClose={onClose}>
      {data.preview === "image" && (
        <div className={styles.picture}>
          <ImagePreview
            attachmentId={data.attachment_id}
            name={name}
            onOpen={() => setLarge(true)}
          />
        </div>
      )}
      <dl className={styles.fields}>
        <div className={styles.field}>
          <dt>Aufnahme</dt>
          <dd>{takenText(data)}</dd>
        </div>
        <div className={styles.field}>
          <dt>Gerät</dt>
          <dd>{data.device ?? "unbekannt"}</dd>
        </div>
        {data.nearest && (
          <div className={styles.field}>
            <dt>Nächster Ort</dt>
            <dd>
              {nearestText(data.nearest)}
              <span className={styles.muted}>{` · ${regionText(data.nearest)}`}</span>
            </dd>
          </div>
        )}
        <div className={styles.field}>
          <dt>Koordinaten</dt>
          <dd>
            <span className={styles.value}>{coordinatesText(data.latitude, data.longitude)}</span>
            {data.altitude !== null && (
              <span
                className={styles.muted}
              >{` · ${data.altitude.toLocaleString("de-DE")} m`}</span>
            )}{" "}
            <a
              href={openStreetMapUrl({ latitude: data.latitude, longitude: data.longitude })}
              target="_blank"
              rel="noopener noreferrer"
            >
              auf OpenStreetMap ansehen
            </a>
          </dd>
        </div>
      </dl>
      <p className={styles.links}>
        <Link to={documentPath(data.document_id)}>Zum Dokument</Link>
      </p>

      <section className={styles.section} aria-label="Mails mit diesem Foto">
        <h3 className={styles.sectionTitle}>
          {countText(data.mail_count, "Mail", "Mails")} mit diesem Foto
        </h3>
        <MailList mails={data.mails} />
        {data.mail_count > data.mails.length && (
          <Link to={documentMailsHref(data.document_id)} className={styles.more}>
            Alle {formatNumber(data.mail_count)} in der Mailliste
          </Link>
        )}
      </section>

      <NearbyPhotos photo={data} params={params} onPick={onPick} />
      {data.device && <DevicePhotos photo={data} params={params} onPick={onPick} />}

      {large && (
        <ImageViewer
          attachmentId={data.attachment_id}
          name={name}
          onClose={() => setLarge(false)}
        />
      )}
    </Frame>
  );
}

/** One photo of a panel's list; the photo shown is marked, the others are picked by a click. */
function PhotoRow({
  item,
  current,
  detail,
  onPick,
}: {
  item: PhotoListItem;
  current: boolean;
  detail: string;
  onPick: Pick;
}) {
  const name = item.name || "(ohne Dateinamen)";
  return (
    <li>
      <button
        type="button"
        className={cx(styles.photo, current && styles.current)}
        aria-current={current || undefined}
        disabled={current}
        onClick={() =>
          onPick(
            { kind: "photo", id: item.document_id },
            { lat: item.latitude, lon: item.longitude, zoom: 13 },
          )
        }
      >
        <span className={styles.photoName}>{name}</span>
        <span className={styles.photoDetail}>{detail}</span>
      </button>
    </li>
  );
}

/** "Fotos im Umkreis" (D248): the photos within a radius of this one, nearest first. */
function NearbyPhotos({
  photo,
  params,
  onPick,
}: {
  photo: PhotoDetail;
  params: PlaceParams;
  onPick: Pick;
}) {
  const [radius, setRadius] = useState<number>(DEFAULT_RADIUS_KM);
  const list = usePhotoList({
    ...params,
    lat: photo.latitude,
    lon: photo.longitude,
    radius_km: radius,
    limit: PANEL_PHOTOS,
  });
  const others = list.data?.items.filter((item) => item.document_id !== photo.document_id) ?? [];
  const count = list.data ? list.data.total - (list.data.items.length - others.length) : null;
  return (
    <section className={styles.section} aria-label="Fotos im Umkreis">
      <h3 className={styles.sectionTitle}>Fotos im Umkreis</h3>
      <div className={styles.radii} role="group" aria-label="Umkreis">
        {RADII_KM.map((km) => (
          <button
            key={km}
            type="button"
            className={cx(styles.radius, km === radius && styles.radiusOn)}
            aria-pressed={km === radius}
            onClick={() => setRadius(km)}
          >
            {formatKm(km)}
          </button>
        ))}
      </div>
      {list.isPending ? (
        <Loading label="Fotos werden gesucht" />
      ) : list.isError ? (
        <p className={styles.note}>Die Fotos im Umkreis lassen sich gerade nicht laden.</p>
      ) : others.length === 0 ? (
        <p className={styles.note}>{`Keine weiteren Fotos im Umkreis von ${formatKm(radius)}.`}</p>
      ) : (
        <>
          <p className={styles.note}>
            {`${countText(count ?? others.length, "weiteres Foto", "weitere Fotos")} im Umkreis von ${formatKm(radius)}`}
          </p>
          <ol className={styles.photos}>
            {others.map((item) => (
              <PhotoRow
                key={item.document_id}
                item={item}
                current={false}
                detail={[
                  item.distance_km !== null && formatKm(item.distance_km),
                  item.taken_at && formatDate(item.taken_at),
                ]
                  .filter(Boolean)
                  .join(" · ")}
                onPick={onPick}
              />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

/** "Fotos dieses Geräts" (D248): the device's photos by capture time, this one marked. */
function DevicePhotos({
  photo,
  params,
  onPick,
}: {
  photo: PhotoDetail;
  params: PlaceParams;
  onPick: Pick;
}) {
  const list = usePhotoList({ ...params, device: photo.device ?? undefined, limit: PANEL_PHOTOS });
  const items = list.data?.items ?? [];
  return (
    <section className={styles.section} aria-label="Fotos dieses Geräts">
      <h3 className={styles.sectionTitle}>Fotos dieses Geräts</h3>
      {list.isPending ? (
        <Loading label="Fotos werden gesucht" />
      ) : list.isError ? (
        <p className={styles.note}>Die Fotos dieses Geräts lassen sich gerade nicht laden.</p>
      ) : (
        <>
          <p className={styles.note}>
            {`${countText(list.data.total, "Foto", "Fotos")} mit ${photo.device}, nach Aufnahmezeit`}
            {list.data.total > items.length && `; die ersten ${formatNumber(items.length)}`}
          </p>
          <ol className={styles.photos}>
            {items.map((item) => (
              <PhotoRow
                key={item.document_id}
                item={item}
                current={item.document_id === photo.document_id}
                detail={
                  item.taken_at
                    ? takenText({ taken_at: item.taken_at, taken_text: null })
                    : "ohne Aufnahmezeit"
                }
                onPick={onPick}
              />
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

const DETAIL_KIND_LABELS: Record<TextPlace["detail"], string> = {
  city: "Ort",
  country: "Land",
};

/** A place named in mails or their attachments (D242): what its point stands for, and the mails
 *  mentioning it in the mail list (D86). Without the place in the layer (filtered out or beyond
 *  its limit) the links still lead there. */
export function TextPlacePanel({
  id,
  place,
  exact,
  state,
  onClose,
}: {
  id: number;
  place: TextPlace | undefined;
  exact: boolean;
  state: PlacesState;
  onClose: () => void;
}) {
  return (
    <Frame kind="Ort aus Texten" title={place?.label ?? `Ort #${id}`} onClose={onClose}>
      {place ? (
        <dl className={styles.fields}>
          <div className={styles.field}>
            <dt>Auf der Karte</dt>
            <dd>
              {place.place}
              <span className={styles.muted}>{` · ${DETAIL_KIND_LABELS[place.detail]}`}</span>
            </dd>
          </div>
          <div className={styles.field}>
            <dt>Genannt in</dt>
            <dd>
              {countText(place.mails, "Mail", "Mails")}
              {!exact && <span className={styles.muted}> (in einer Stichprobe gezählt)</span>}
            </dd>
          </div>
          <div className={styles.field}>
            <dt>Koordinaten</dt>
            <dd className={styles.value}>{coordinatesText(place.lat, place.lon)}</dd>
          </div>
        </dl>
      ) : (
        <p className={styles.note}>Mit den aktuellen Filtern ist dieser Ort nicht auf der Karte.</p>
      )}
      <p className={styles.links}>
        <Link to={textPlaceMailsHref(state, id)}>Mails, die diesen Ort nennen</Link>
        <Link to={entityPath(id)}>Zur Entität</Link>
      </p>
    </Frame>
  );
}

/** The place of invitations (D243): the locations as the invitations write them, and their
 *  latest events with the mails that carry them. */
export function EventPlacePanel({
  place,
  onClose,
}: {
  place: EventPlace | undefined;
  onClose: () => void;
}) {
  if (!place) {
    return (
      <Frame kind="Ort von Terminen" title="Ort von Terminen" onClose={onClose}>
        <p className={styles.note}>Mit den aktuellen Filtern ist dieser Ort nicht auf der Karte.</p>
      </Frame>
    );
  }
  const span =
    place.first && place.last
      ? place.first.slice(0, 10) === place.last.slice(0, 10)
        ? formatDate(place.first)
        : `${formatDate(place.first)} bis ${formatDate(place.last)}`
      : null;
  return (
    <Frame kind="Ort von Terminen" title={place.place} onClose={onClose}>
      <p className={styles.note}>
        {countText(place.events, "Termin", "Termine")}
        {span && `, ${span}`}
      </p>
      <section className={styles.section} aria-label="So steht es in den Einladungen">
        <h3 className={styles.sectionTitle}>So steht es in den Einladungen</h3>
        <ul className={styles.locations}>
          {place.locations.map((location) => (
            <li key={location}>{location}</li>
          ))}
        </ul>
      </section>
      <section className={styles.section} aria-label="Termine">
        <h3 className={styles.sectionTitle}>
          {place.events > place.samples.length
            ? `Die letzten ${formatNumber(place.samples.length)} Termine`
            : "Termine"}
        </h3>
        <ul className={styles.events}>
          {place.samples.map((event) => (
            <li key={event.event_id} className={styles.event}>
              <span className={styles.eventHead}>
                <span className={styles.eventKind}>{EVENT_LABELS[event.kind]}</span>
                {eventStartText(event) ?? "ohne Zeit"}
              </span>
              <span className={styles.subject}>{event.summary || "(ohne Titel)"}</span>
              {event.location && <span className={styles.muted}>{event.location}</span>}
              <Link to={`/mails/${event.mail_id}`} className={styles.eventMail}>
                Zur Mail
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </Frame>
  );
}

const COUNT_LABELS: [keyof PlaceCounts, string][] = [
  ["found", "mit Punkt auf der Karte"],
  ["ambiguous", "mehrdeutig, ohne Punkt"],
  ["unknown", "nicht in den Ortslisten"],
  ["waiting", "noch nicht bestimmt"],
];

function Counts({ title, counts }: { title: string; counts: PlaceCounts }) {
  return (
    <div className={styles.field}>
      <dt>{title}</dt>
      <dd>
        <ul className={styles.counts}>
          {COUNT_LABELS.filter(([key]) => key !== "waiting" || counts.waiting > 0).map(
            ([key, label]) => (
              <li key={key}>
                <span className={styles.countValue}>{formatNumber(counts[key])}</span> {label}
              </li>
            ),
          )}
        </ul>
      </dd>
    </div>
  );
}

/** The side without a point: what the archive has to show on the map. */
export function PlaceOverview({ summary }: { summary: PlaceSummary | undefined }) {
  const notice = summary && placesStepNotice(summary);
  return (
    <section className={styles.panel} aria-label="Überblick">
      <div className={styles.heading}>
        <span className={styles.kind}>Überblick</span>
        <h2 className={styles.title}>Orte im Archiv</h2>
      </div>
      {!summary ? (
        <Loading label="Überblick wird geladen" />
      ) : (
        <dl className={styles.fields}>
          <div className={styles.field}>
            <dt>Fotos mit Position</dt>
            <dd>
              {formatNumber(summary.photos)}
              <span className={styles.muted}>
                {`, ${formatNumber(summary.photos_dated)} mit Aufnahmezeit, von ${countText(summary.devices.length, "Gerät", "Geräten")}`}
              </span>
            </dd>
          </div>
          <Counts title="Orte aus Texten" counts={summary.texts} />
          <Counts title="Orte von Terminen" counts={summary.events} />
        </dl>
      )}
      {notice && <p className={styles.notice}>{notice}</p>}
      <p className={styles.note}>
        Ein Klick auf einen Punkt zeigt ihn hier, ein Klick auf eine Zahl zoomt hinein. Gezeigt ist,
        was die Mails der Filter links tragen oder nennen.
      </p>
    </section>
  );
}
