"""manifest.json and manifest.csv of an export (D62): the export and, per mail, what the archive
knows about it and the files that hold it.

The models below are the format of manifest.json, version 1; times are ISO 8601 in UTC. Each
attachment carries every metadata field its file states about itself (D167), as found. The CSV
holds the same per mail, in German, semicolon-separated UTF-8 with a byte order mark as the mail
list's CSV (D25), below a few lines about the export. Research data (review status, bookmark,
tags, Akten, notes), the signals of each mail (D139), the labels of its participants (D157, in
manifest.json) and the selection the mails were chosen by appear only when the export includes
the research data: they are internal assessments or, as the selection and the word field
signals do, show what the team looks for (source protection). Whether an attachment is
encrypted (D233) is always stated; the password that opened it, with where it was found, only
when the export includes the passwords (D208), as they then stand in plain text.
"""

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from mailrobbe.api.mails import CSV_BOM, csv_cell
from mailrobbe.api.schemas import MailResearch, MetadataValue, PersonLabel, PersonRef
from mailrobbe.enums import (
    DkimReason,
    DkimStatus,
    DnsStatus,
    DocumentMetadataStatus,
    DocumentProtection,
    KeyOrigin,
    ParticipationRole,
    PasswordTier,
    ReviewStatus,
)
from mailrobbe.export.pdf import ORIGIN_TEXTS, REVIEW_TEXTS
from mailrobbe.export.records import AttachmentMetadata, AttachmentPassword, ExportMail

MailError = Literal[
    "not_in_archive",  # no mail of the archive has this content any more
    "source_missing",  # the MBOX file cannot be read
    "source_changed",  # the bytes at the stored offset are not the imported mail any more
]
ERROR_TEXTS: dict[MailError, str] = {
    "not_in_archive": "Keine Mail im Archiv hat diesen Inhalt (mehr).",
    "source_missing": "Die MBOX-Datei ist nicht lesbar.",
    "source_changed": "An der gespeicherten Stelle der MBOX-Datei steht nicht mehr diese Mail.",
}


class ManifestFile(BaseModel):
    path: str  # relative to the export's folder
    size: int  # bytes
    sha256: str


class ManifestFiles(BaseModel):
    eml: ManifestFile  # the message as stored; its SHA-256 equals ManifestMail.sha256
    pdf: ManifestFile  # the reading copy


class ManifestLabel(BaseModel):
    """The team's label the participant shows (D156); not part of the mail."""

    name: str | None  # Klarname
    role: str | None
    note: str | None


class ManifestAddress(BaseModel):
    email: str
    name: str | None  # the display name used in this mail, else the person's
    label: ManifestLabel | None = None  # D157: only with research data, else always None


class ManifestSource(BaseModel):
    file: str  # MBOX file, relative to the archive's directory
    byte_offset: int  # of the record's "From " line
    byte_length: int  # of the record


class ManifestSignature(BaseModel):
    index: int  # order of the DKIM-Signature fields, topmost first, from 0
    result: DkimStatus
    reason: DkimReason | None  # why it did not pass
    domain: str | None  # d=
    selector: str | None  # s=
    algorithm: str | None
    key_bits: int | None
    aligned: bool | None  # d= fits the From domain (D12)
    signed_at: datetime | None  # t=
    checked_at: datetime
    key_status: DnsStatus | None  # the cached DNS answer for the key; None: none cached
    key_record: str | None  # the TXT record, when found
    key_fetched_at: datetime | None
    # The key the result rests on (D100, D105); None when it rests on none. A key from another
    # source than today's DNS has its folder schluessel/<selector>._domainkey.<domain>/<key_sha256>/
    # with one beleg-<id>.json per evidence id.
    key_origin: KeyOrigin | None = None
    key_sha256: str | None = None  # SHA-256 of the public key (DER), its identity across sources
    evidence: list[int] = []


class ManifestDkim(BaseModel):
    status: DkimStatus | None  # the mail's result, the best of its signatures; None: unchecked
    signatures: list[ManifestSignature]


class ManifestMetadata(BaseModel):
    """What the attachment's file says about itself (D167): every field the import's metadata
    step found, as found and never checked, grouped by where it stands in the file (exif, gps,
    xmp, png, pdf, pdf_custom, office, office_custom, odf, odf_custom), keys as in
    attachments.metadata.model."""

    status: DocumentMetadataStatus  # pending: not read yet; unsupported: a format not read
    error: str | None  # English: why reading failed, or the part found damaged
    fields: dict[str, dict[str, MetadataValue]]  # source -> key -> value; {} without any


class ManifestPassword(BaseModel):
    """The password that opened the attachment (D236) and where it was found (D208)."""

    value: str  # in plain text
    tier: PasswordTier  # mail, thread, contacts, attachments, opened, archive, manual or typed
    found_by: str | None  # the editor who typed it in (D54), not verified
    mail_id: int | None  # the archive's mail it was found in
    context: str  # the line(s) around it as written; "" for one typed in


class ManifestAttachment(BaseModel):
    filename: str | None
    mime_type: str
    size: int  # bytes, decoded
    sha256: str | None  # None above the import's hash limit
    file: ManifestFile | None = None  # its own file in anhaenge/; not exported yet (D62)
    metadata: ManifestMetadata | None = None  # None: no document assigned yet (D70)
    # locked: encrypted, no password known; open: a password opened it (D233); None: neither
    protection: DocumentProtection | None = None
    password: ManifestPassword | None = None  # only when the export includes the passwords


class ManifestNote(BaseModel):
    author: str | None
    created_at: datetime
    updated_at: datetime
    text: str


class ManifestResearch(BaseModel):
    review: ReviewStatus | None  # None: unreviewed
    review_by: str | None
    review_at: datetime | None
    flagged: bool
    flagged_by: str | None
    flagged_at: datetime | None
    tags: list[str]
    collections: list[str]  # Akten
    notes: list[ManifestNote]  # oldest first


class ManifestError(BaseModel):
    code: MailError
    message: str  # German


class ManifestMail(BaseModel):
    number: int  # from 1, in the export's order
    folder: str | None  # NNNN-<mail id>; None when the mail has an error and no files
    mail_id: int | None  # the original with this content; None when none is left
    sha256: str  # SHA-256 of the message recorded at import
    message_id: str | None = None
    in_reply_to: str | None = None
    date: datetime | None = None
    subject: str | None = None
    from_: list[ManifestAddress] = Field(default=[], serialization_alias="from")
    to: list[ManifestAddress] = []
    cc: list[ManifestAddress] = []
    bcc: list[ManifestAddress] = []
    source: ManifestSource | None = None
    files: ManifestFiles | None = None
    dkim: ManifestDkim | None = None
    attachments: list[ManifestAttachment] = []
    error: ManifestError | None = None
    research: ManifestResearch | None = None  # left out of the files without research data
    # The German names of the stored signals (D139) in display order; like research, left out
    # of the files without research data.
    signals: list[str] = []


class ManifestExport(BaseModel):
    id: int
    label: str
    created_by: str | None  # the editor name given in Mailrobbe (D54), not verified
    created_at: datetime
    include_research: bool
    mails: int
    errors: int  # mails listed with an error instead of files
    include_passwords: bool = False  # the passwords that opened attachments (D208)
    selection: dict[str, Any] | None = None  # as requested; only with research data


class Manifest(BaseModel):
    format: Literal["mailrobbe-export"] = "mailrobbe-export"
    version: Literal[1] = 1
    export: ManifestExport
    mails: list[ManifestMail]


def mail_entry(
    number: int,
    sha256: str,
    mail: ExportMail | None,
    research: MailResearch | None,
    *,
    folder: str | None = None,
    files: ManifestFiles | None = None,
    error: MailError | None = None,
    signals: Sequence[str] = (),
    passwords: bool = False,
) -> ManifestMail:
    """signals: the German names of the mail's signals (ExportMail.signal_names), kept only
    with research data; passwords: whether the export includes the passwords (D208)."""
    entry = ManifestMail(
        number=number,
        folder=folder,
        mail_id=None if mail is None else mail.id,
        sha256=sha256,
        files=files,
        error=None if error is None else ManifestError(code=error, message=ERROR_TEXTS[error]),
        research=None if research is None else _research(research),
    )
    if mail is None:
        return entry
    entry.message_id = mail.message_id
    entry.in_reply_to = mail.in_reply_to
    entry.date = mail.date
    entry.subject = mail.subject
    labels = mail.labels if research is not None else {}
    entry.from_ = _addresses(mail.participants.get(ParticipationRole.FROM, []), labels)
    entry.to = _addresses(mail.participants.get(ParticipationRole.TO, []), labels)
    entry.cc = _addresses(mail.participants.get(ParticipationRole.CC, []), labels)
    entry.bcc = _addresses(mail.participants.get(ParticipationRole.BCC, []), labels)
    entry.source = ManifestSource(
        file=mail.source.path,
        byte_offset=mail.source.byte_offset,
        byte_length=mail.source.byte_length,
    )
    entry.dkim = ManifestDkim(
        status=mail.dkim_status,
        signatures=[
            ManifestSignature(
                index=s.index,
                result=s.status,
                reason=s.reason,
                domain=s.domain,
                selector=s.selector,
                algorithm=s.algorithm,
                key_bits=s.key_bits,
                aligned=s.aligned,
                signed_at=s.signed_at,
                checked_at=s.checked_at,
                key_status=s.key_status,
                key_record=s.key_record,
                key_fetched_at=s.key_fetched_at,
                key_origin=s.key_origin,
                key_sha256=s.key_sha256,
                evidence=list(s.evidence),
            )
            for s in mail.signatures
        ],
    )
    entry.attachments = [
        ManifestAttachment(
            filename=a.filename,
            mime_type=a.mime_type,
            size=a.size,
            sha256=a.sha256,
            metadata=_metadata(mail.attachment_metadata.get(a.id)),
            protection=a.protection,
            password=_password(mail.attachment_passwords.get(a.id)) if passwords else None,
        )
        for a in mail.attachments
    ]
    if research is not None:
        entry.signals = list(signals)
    return entry


def _metadata(found: AttachmentMetadata | None) -> ManifestMetadata | None:
    if found is None:
        return None
    return ManifestMetadata(status=found.status, error=found.error, fields=found.fields)


def _password(found: AttachmentPassword | None) -> ManifestPassword | None:
    if found is None:
        return None
    return ManifestPassword(
        value=found.value,
        tier=found.tier,
        found_by=found.found_by,
        mail_id=found.mail_id,
        context=found.context,
    )


def _addresses(
    people: Iterable[PersonRef], labels: Mapping[int, PersonLabel]
) -> list[ManifestAddress]:
    return [
        ManifestAddress(email=person.email, name=person.name, label=_label(labels, person))
        for person in people
    ]


def _label(labels: Mapping[int, PersonLabel], person: PersonRef) -> ManifestLabel | None:
    label = labels.get(person.person_id)
    if label is None:
        return None
    return ManifestLabel(name=label.name, role=label.role, note=label.note)


def _research(research: MailResearch) -> ManifestResearch:
    mark = research.mark
    return ManifestResearch(
        review=mark.review,
        review_by=mark.review_by,
        review_at=mark.review_at,
        flagged=mark.flagged,
        flagged_by=mark.flagged_by,
        flagged_at=mark.flagged_at,
        tags=[tag.name for tag in research.tags],
        collections=[collection.name for collection in research.collections],
        notes=[
            ManifestNote(
                author=note.author,
                created_at=note.created_at,
                updated_at=note.updated_at,
                text=note.body,
            )
            for note in research.notes
        ],
    )


def manifest_json(manifest: Manifest) -> bytes:
    export: dict[str, Any] = {}
    mail: dict[str, Any] = {}
    if not manifest.export.include_research:
        export["selection"] = True
        mail.update(research=True, signals=True)
    if not manifest.export.include_passwords:
        mail["attachments"] = {"__all__": {"password"}}
    exclude = {"export": export, "mails": {"__all__": mail}}
    return (manifest.model_dump_json(indent=2, by_alias=True, exclude=exclude) + "\n").encode()


CSV_HEADER = (
    "Nr.",
    "Ordner",
    "Mail-ID",
    "SHA-256 mail.eml",
    "SHA-256 mail.pdf",
    "Fehler",
    "Datum (UTC)",
    "Von",
    "An",
    "Cc",
    "Bcc",
    "Betreff",
    "Message-ID",
    "In-Reply-To",
    "MBOX-Datei",
    "Offset",
    "Länge",
    "DKIM",
    "DKIM-Signaturen",
    "Anhänge",
)
CSV_RESEARCH_HEADER = ("Bewertung", "Markiert", "Schlagworte", "Akten", "Notizen", "Signale")


def manifest_csv(manifest: Manifest) -> bytes:
    export = manifest.export
    research = export.include_research
    buffer = io.StringIO()
    buffer.write(CSV_BOM)
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Mailrobbe-Export", str(export.id)])
    writer.writerow(["Bezeichnung", csv_cell(export.label)])
    writer.writerow(["Erstellt von", csv_cell(export.created_by)])
    writer.writerow(["Erstellt am (UTC)", _time(export.created_at)])
    writer.writerow(["Mails", str(export.mails)])
    writer.writerow(["Davon mit Fehler", str(export.errors)])
    writer.writerow(["Rechercheangaben", "ja" if research else "nein"])
    writer.writerow(["Kennwörter", "ja" if export.include_passwords else "nein"])
    writer.writerow([])
    writer.writerow(CSV_HEADER + (CSV_RESEARCH_HEADER if research else ()))
    for mail in manifest.mails:
        row = [
            str(mail.number),
            mail.folder or "",
            "" if mail.mail_id is None else str(mail.mail_id),
            mail.sha256,
            mail.files.pdf.sha256 if mail.files else "",
            mail.error.message if mail.error else "",
            _time(mail.date),
            csv_cell(_people(mail.from_)),
            csv_cell(_people(mail.to)),
            csv_cell(_people(mail.cc)),
            csv_cell(_people(mail.bcc)),
            csv_cell(mail.subject),
            csv_cell(mail.message_id),
            csv_cell(mail.in_reply_to),
            csv_cell(mail.source.file if mail.source else None),
            str(mail.source.byte_offset) if mail.source else "",
            str(mail.source.byte_length) if mail.source else "",
            _dkim_status(mail.dkim),
            csv_cell(_signatures(mail.dkim)),
            csv_cell(_attachments(mail.attachments)),
        ]
        if research:
            row += _research_cells(mail)
        writer.writerow(row)
    return buffer.getvalue().encode()


def _time(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _people(addresses: list[ManifestAddress]) -> str:
    return ", ".join(f"{a.name} <{a.email}>" if a.name else a.email for a in addresses)


def _dkim_status(dkim: ManifestDkim | None) -> str:
    if dkim is None:
        return ""
    return "unchecked" if dkim.status is None else dkim.status.value


def _signatures(dkim: ManifestDkim | None) -> str:
    if dkim is None:
        return ""
    texts = []
    for s in dkim.signatures:
        result = s.result.value + (f" ({s.reason.value})" if s.reason else "")
        key = {
            DnsStatus.FOUND: "Schlüssel gefunden",
            DnsStatus.NOT_FOUND: "Schlüssel nicht gefunden",
            DnsStatus.TEMP_ERROR: "Schlüsselabfrage fehlgeschlagen",
            None: "keine Schlüsselabfrage gespeichert",
        }[s.key_status]
        if s.key_origin:
            key += f", Herkunft des Schlüssels: {ORIGIN_TEXTS[s.key_origin]}"
        if s.key_sha256:
            key += f", Schlüssel-SHA-256 {s.key_sha256}"
        if s.evidence:
            key += ", Belege " + ", ".join(map(str, s.evidence))
        texts.append(
            f"{s.index + 1}: {result}, d={s.domain or ''}, s={s.selector or ''}, {key}, "
            f"geprüft {_time(s.checked_at)}"
        )
    return "; ".join(texts)


def _attachments(attachments: list[ManifestAttachment]) -> str:
    return "; ".join(
        f"{a.filename or '(ohne Namen)'} ({a.mime_type}, {a.size} Bytes{_protection(a)})"
        for a in attachments
    )


def _protection(attachment: ManifestAttachment) -> str:
    match attachment.protection:
        case DocumentProtection.LOCKED:
            return ", verschlüsselt, Kennwort unbekannt"
        case DocumentProtection.OPEN if attachment.password is not None:
            return f", verschlüsselt, Kennwort: {attachment.password.value}"
        case DocumentProtection.OPEN:
            return ", verschlüsselt, mit Kennwort geöffnet"
    return ""


def _research_cells(mail: ManifestMail) -> list[str]:
    research = mail.research
    if research is None:
        return [""] * len(CSV_RESEARCH_HEADER)
    review = REVIEW_TEXTS[research.review] if research.review else "Ungesichtet"
    if research.review_at:
        review += f" ({research.review_by or 'ohne Namen'}, {_time(research.review_at)})"
    notes = " | ".join(
        f"{note.author or 'ohne Namen'}, {_time(note.created_at)}: {note.text}"
        for note in research.notes
    )
    return [
        review,
        "ja" if research.flagged else "nein",
        csv_cell(", ".join(research.tags)),
        csv_cell(", ".join(research.collections)),
        csv_cell(notes),
        csv_cell(", ".join(mail.signals)),  # as in the mail list's CSV (D139)
    ]
