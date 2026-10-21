"""What an attachment is (D71): its file format, and from that its kind and whether its text can
be extracted. The one place that decides it, for finalize (documents.py), the text extraction and
the API.

classify looks at the content's first bytes when it has them, then at the file name's extension,
then at the declared MIME type: mail programs often declare application/octet-stream, and a
decisive signature (%PDF-, PNG, ...) wins over a misleading name. ZIP and OLE containers say only
that they are containers; which Office format they hold comes from the name or the MIME type.
"""

import re
from dataclasses import dataclass

from mailrobbe.enums import DocumentKind

HEAD_SIZE = 4096  # bytes of the content classify looks at


@dataclass(frozen=True, slots=True)
class FileFormat:
    name: str  # stable key, e.g. "pdf", "docx"; the extractors dispatch on it
    kind: DocumentKind
    extractable: bool  # the text extraction reads this format


def _formats(kind: DocumentKind, extractable: bool, *names: str) -> dict[str, FileFormat]:
    return {name: FileFormat(name, kind, extractable) for name in names}


K = DocumentKind
FORMATS: dict[str, FileFormat] = {
    **_formats(K.PDF, True, "pdf"),
    **_formats(K.DOCUMENT, True, "docx", "odt", "rtf"),
    **_formats(K.DOCUMENT, False, "doc"),
    **_formats(K.SPREADSHEET, True, "xlsx", "ods", "csv"),
    **_formats(K.SPREADSHEET, False, "xls"),
    **_formats(K.PRESENTATION, True, "pptx", "odp"),
    **_formats(K.PRESENTATION, False, "ppt"),
    **_formats(K.TEXT, True, "text", "html", "xml", "json", "calendar", "vcard"),
    **_formats(K.EMAIL, True, "eml"),
    **_formats(K.EMAIL, False, "msg"),
    **_formats(K.ARCHIVE, True, "zip"),  # the text is the list of its members' names
    **_formats(K.ARCHIVE, False, "archive"),
    **_formats(K.IMAGE, False, "image"),
    **_formats(K.MEDIA, False, "media"),
    **_formats(K.OTHER, False, "ole", "other"),
}

_EXTENSIONS = {
    **dict.fromkeys(("pdf",), "pdf"),
    **dict.fromkeys(("docx", "docm", "dotx", "dotm"), "docx"),
    **dict.fromkeys(("xlsx", "xlsm", "xltx", "xltm"), "xlsx"),
    **dict.fromkeys(("pptx", "pptm", "ppsx", "ppsm", "potx", "potm"), "pptx"),
    **dict.fromkeys(("odt", "ott"), "odt"),
    **dict.fromkeys(("ods", "ots"), "ods"),
    **dict.fromkeys(("odp", "otp"), "odp"),
    **dict.fromkeys(("rtf",), "rtf"),
    **dict.fromkeys(("doc", "dot"), "doc"),
    **dict.fromkeys(("xls", "xlt"), "xls"),
    **dict.fromkeys(("ppt", "pps", "pot"), "ppt"),
    **dict.fromkeys(("csv", "tsv", "tab"), "csv"),
    **dict.fromkeys(("txt", "text", "log", "md", "markdown", "asc", "nfo"), "text"),
    **dict.fromkeys(("html", "htm", "xhtml", "mht", "mhtml"), "html"),
    **dict.fromkeys(("xml",), "xml"),
    **dict.fromkeys(("json",), "json"),
    **dict.fromkeys(("ics", "ical", "vcs"), "calendar"),
    **dict.fromkeys(("vcf", "vcard"), "vcard"),
    **dict.fromkeys(("eml",), "eml"),
    **dict.fromkeys(("msg",), "msg"),
    **dict.fromkeys(("zip",), "zip"),
    **dict.fromkeys(("rar", "7z", "gz", "tgz", "tar", "bz2", "xz", "cab", "arj"), "archive"),
    **dict.fromkeys(
        ("jpg", "jpeg", "jpe", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "svg", "ico"),
        "image",
    ),
    **dict.fromkeys(
        ("mp3", "wav", "m4a", "aac", "ogg", "oga", "wma", "amr", "flac", "opus"), "media"
    ),
    **dict.fromkeys(
        ("mp4", "m4v", "mov", "avi", "mkv", "wmv", "webm", "mpg", "mpeg", "3gp"), "media"
    ),
}

_OOXML = "application/vnd.openxmlformats-officedocument."
_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/x-pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.ms-word.document.macroenabled.12": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.ms-excel.sheet.macroenabled.12": "xlsx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.ms-powerpoint.presentation.macroenabled.12": "pptx",
    "application/vnd.ms-outlook": "msg",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "text/csv": "csv",
    "text/tab-separated-values": "csv",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/xml": "xml",
    "application/xml": "xml",
    "application/json": "json",
    "text/calendar": "calendar",
    "text/vcard": "vcard",
    "text/x-vcard": "vcard",
    "text/directory": "vcard",
    "message/rfc822": "eml",
    "application/zip": "zip",
    "application/x-zip-compressed": "zip",
    "application/x-zip": "zip",
    "application/vnd.rar": "archive",
    "application/x-rar-compressed": "archive",
    "application/x-7z-compressed": "archive",
    "application/gzip": "archive",
    "application/x-gzip": "archive",
    "application/x-tar": "archive",
    "application/x-bzip2": "archive",
}

# Formats a ZIP or an OLE container can hold; another name or type leaves it a container.
_IN_ZIP = frozenset({"docx", "xlsx", "pptx", "odt", "ods", "odp", "zip"})
_IN_OLE = frozenset({"doc", "xls", "ppt", "msg", "docx", "xlsx", "pptx"})  # OOXML: encrypted
_ODF_MIMETYPE = re.compile(
    rb"mimetypeapplication/vnd\.oasis\.opendocument\.(text|spreadsheet|presentation)"
)
_ODF = {b"text": "odt", b"spreadsheet": "ods", b"presentation": "odp"}
_SIGNATURES: tuple[tuple[bytes, int, str], ...] = (  # (bytes, offset, format)
    (b"{\\rtf", 0, "rtf"),
    (b"\x89PNG\r\n\x1a\n", 0, "image"),
    (b"\xff\xd8\xff", 0, "image"),
    (b"GIF87a", 0, "image"),
    (b"GIF89a", 0, "image"),
    (b"II*\x00", 0, "image"),
    (b"MM\x00*", 0, "image"),
    (b"Rar!\x1a\x07", 0, "archive"),
    (b"7z\xbc\xaf\x27\x1c", 0, "archive"),
    (b"\x1f\x8b\x08", 0, "archive"),
    (b"BZh", 0, "archive"),
    (b"\xfd7zXZ\x00", 0, "archive"),
    (b"ID3", 0, "media"),
    (b"OggS", 0, "media"),
    (b"fLaC", 0, "media"),
    (b"\x1aE\xdf\xa3", 0, "media"),
    (b"ftyp", 4, "media"),
)
_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def classify(filename: str | None, mime_type: str, head: bytes = b"") -> FileFormat:
    """The format of a file from its name, declared MIME type and, when given, first bytes."""
    by_name = _by_extension(filename)
    by_type = _by_mime_type(mime_type)
    declared = by_name or by_type
    sniffed = _by_signature(head)
    if sniffed == "zip":
        name = by_name if by_name in _IN_ZIP else by_type if by_type in _IN_ZIP else "zip"
        return FORMATS[name]
    if sniffed == "ole":
        name = by_name if by_name in _IN_OLE else by_type if by_type in _IN_OLE else "ole"
        return FORMATS[name]
    return FORMATS[sniffed or declared or "other"]


def _by_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    stem, dot, extension = filename.strip().rpartition(".")
    if not dot or not stem:
        return None
    return _EXTENSIONS.get(extension.lower())


def _by_mime_type(mime_type: str) -> str | None:
    value = mime_type.strip().lower().partition(";")[0].strip()
    if value in _MIME_TYPES:
        return _MIME_TYPES[value]
    if value.startswith(_OOXML):
        kinds = (
            ("wordprocessingml", "docx"),
            ("spreadsheetml", "xlsx"),
            ("presentationml", "pptx"),
        )
        for prefix, name in kinds:
            if value.startswith(prefix, len(_OOXML)):
                return name
    major = value.partition("/")[0]
    if major == "image":
        return "image"
    if major in ("audio", "video"):
        return "media"
    if major == "text":
        return "text"
    return None


def _by_signature(head: bytes) -> str | None:
    """A format the first bytes prove; "zip" and "ole" for containers."""
    if not head:
        return None
    if b"%PDF-" in head[:1024]:
        return "pdf"
    if head.startswith(_ZIP):
        match = _ODF_MIMETYPE.search(head[:256])
        return _ODF[match.group(1)] if match else "zip"
    if head.startswith(_OLE):
        return "ole"
    if head.startswith(b"RIFF") and head[8:12] in (b"WEBP", b"WAVE", b"AVI "):
        return "image" if head[8:12] == b"WEBP" else "media"
    for signature, offset, name in _SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return name
    return None
