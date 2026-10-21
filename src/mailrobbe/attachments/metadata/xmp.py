"""XMP (D167): the fields of an XMP packet, in images (JPEG APP1, PNG iTXt, WebP) and PDFs.

XMP is RDF/XML; a property is an element or an attribute of rdf:Description, an array is an
rdf:Seq, rdf:Bag or rdf:Alt of rdf:li. Read are the tool and the dates (xmp:CreatorTool,
CreateDate, ModifyDate, MetadataDate), pdf:Producer and pdf:Keywords, dc:creator, title,
description, rights and subject, the identifiers of xmpMM and the software agents of its
History. Names are matched without their prefix, as XMP writers choose prefixes freely. The
packet is parsed with the safe parser of extract.packages (no document type, no entities) and
read up to MAX_XMP bytes.
"""

from mailrobbe.attachments.extract.base import Damaged
from mailrobbe.attachments.extract.packages import parse_xml
from mailrobbe.attachments.metadata.model import Collector, DateParser

MAX_XMP = 4 * 1024**2

_SIMPLE = {
    "CreatorTool": "creator_tool",
    "CreateDate": "create_date",
    "ModifyDate": "modify_date",
    "MetadataDate": "metadata_date",
    "Producer": "producer",
    "Keywords": "keywords",
    "DocumentID": "document_id",
    "InstanceID": "instance_id",
    "OriginalDocumentID": "original_document_id",
}
_DATES = frozenset({"create_date", "modify_date", "metadata_date"})
_ARRAYS = {
    "creator": "creator",
    "title": "title",
    "description": "description",
    "rights": "rights",
    "subject": "subject",
}
# W3CDTF as XMP writes it: a year, a month, a day, a time with seconds and a fraction, a zone.
W3C_DATE = DateParser(
    r"(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2})"
    r"(?:T(?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:[.,](?P<fraction>\d+))?)?"
    r"(?P<zone>Z|[+-]\d{2}:?\d{2})?)?)?)?"
)


def _local(name: str) -> str:
    return name.rpartition(":")[2]


class _Packet:
    def __init__(self, out: Collector) -> None:
        self.out = out
        self.simple: dict[str, str] = {}
        self.arrays: dict[str, list[str]] = {}
        self.agents: list[str] = []
        self.events = 0
        self._path: list[str] = []
        self._text: list[str] | None = None

    def start(self, name: str, attrs: dict[str, str]) -> None:
        self._path.append(name)
        if name == "Description":
            for key, value in attrs.items():
                local = _local(key)
                if local in _SIMPLE and not key.startswith("xmlns"):
                    self.simple.setdefault(_SIMPLE[local], value)
        elif name == "li" and "History" in self._path:
            self.events += 1
            for key, value in attrs.items():
                if _local(key) == "softwareAgent":
                    self.agents.append(value)
        capture = name in _SIMPLE or name == "softwareAgent" or self._array() is not None
        self._text = [] if capture else None  # a structure inside a value is no value

    def end(self, name: str) -> None:
        array = self._array()
        self._path.pop()
        found, self._text = self._text, None
        if found is None:
            return
        value = "".join(found)
        if array is not None:
            self.arrays.setdefault(array, []).append(value)
        elif name in _SIMPLE:
            self.simple.setdefault(_SIMPLE[name], value)
        elif name == "softwareAgent" and "History" in self._path:
            self.agents.append(value)

    def data(self, text: str) -> None:
        if self._text is not None:
            self._text.append(text)

    def _array(self) -> str | None:
        """The dc array of the rdf:li at the end of the path (dc:creator/rdf:Seq/rdf:li)."""
        path = self._path
        if len(path) >= 3 and path[-1] == "li" and path[-2] in ("Seq", "Bag", "Alt"):
            return _ARRAYS.get(path[-3])
        return None


def read_xmp(data: bytes, out: Collector) -> None:
    """The fields of one XMP packet (see the module docstring); a malformed packet keeps what
    was read before the damage."""
    if len(data) > MAX_XMP:
        out.damaged(f"XMP packet above {MAX_XMP // 1024**2} MiB, not read")
        return
    packet = _Packet(out)
    try:
        parse_xml([data.rstrip(b"\x00 \r\n\t")], packet, "XMP", doctype=False)
    except Damaged as error:
        out.damaged(str(error))
    for key, value in packet.simple.items():
        if key in _DATES:
            out.date("xmp", key, value, W3C_DATE)
        else:
            out.text("xmp", key, value)
    for key, values in packet.arrays.items():
        out.texts("xmp", key, values)
    out.texts("xmp", "history_agents", packet.agents)
    if packet.events:
        out.number("xmp", "history_events", packet.events)
