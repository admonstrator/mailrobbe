"""ZIP archives (D71): the names of their members, one per line, from the central directory.

Members are never decompressed and archives inside are not opened, so a zip bomb costs nothing
here; the names of encrypted members are readable too.
"""

import io
import zipfile
import zlib

from mailrobbe.attachments.extract.base import Damaged, Sink, reason
from mailrobbe.enums import DocumentTextStatus


def extract_zip(data: bytes, sink: Sink) -> DocumentTextStatus | None:
    try:
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    except (zipfile.BadZipFile, zlib.error, EOFError, ValueError, OSError) as error:
        raise Damaged(f"damaged ZIP archive: {reason(error)}") from None
    for name in names:
        sink.line(name)
    return None
