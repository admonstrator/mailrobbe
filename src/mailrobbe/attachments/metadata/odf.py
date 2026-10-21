"""OpenDocument: ODT, ODS and ODP (D167), read from meta.xml (extract.packages).

The children of office:meta: meta:initial-creator (who made it), dc:creator (who saved it last),
meta:creation-date, dc:date (last saved), meta:generator (the program and its build),
meta:editing-cycles, meta:editing-duration (ISO 8601, as found), meta:template (its title and
location), meta:printed-by, meta:print-date, dc:title, dc:subject, dc:description and every
meta:keyword to odf; every meta:user-defined (the file's own properties) under its own name to
odf_custom. A file without meta.xml has no metadata.
"""

from mailrobbe.attachments.extract.packages import Package, attribute
from mailrobbe.attachments.metadata.model import Collector
from mailrobbe.attachments.metadata.office import Children, store

_META = {
    "initial-creator": "initial_creator",
    "creator": "creator",
    "creation-date": "creation_date",
    "date": "date",
    "generator": "generator",
    "editing-cycles": "editing_cycles",
    "editing-duration": "editing_duration",
    "printed-by": "printed_by",
    "print-date": "print_date",
    "title": "title",
    "subject": "subject",
    "description": "description",
}
_DATES = frozenset({"creation_date", "date", "print_date"})
_MEMBER = "meta.xml"


def read_odf(data: bytes, out: Collector) -> None:
    package = Package(data)
    if _MEMBER not in package.names:
        return
    meta = Children("meta")
    package.parse(_MEMBER, meta)
    keywords = []
    for name, attrs, value in meta.found:
        if name in _META:
            key = _META[name]
            if key == "editing_cycles" and value.strip().isdigit():
                out.number("odf", key, int(value.strip()))
            else:
                store(out, "odf", key, value, _DATES)
        elif name == "keyword":
            keywords.append(value)
        elif name == "user-defined" and (own := attribute(attrs, "name")):
            out.text("odf_custom", own, value)
        elif name == "template":
            out.text("odf", "template", attribute(attrs, "title") or attribute(attrs, "href"))
            out.text("odf", "template_location", attribute(attrs, "href"))
    out.texts("odf", "keywords", keywords)
