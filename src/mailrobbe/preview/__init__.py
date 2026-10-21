"""Attachments shown in the browser (D120 to D125): what can be shown, and how it stays isolated.

    kinds       preview_kind: the one place deciding whether and how an attachment is shown
                (image, pdf, html, audio, video); the API's hints and endpoints use it
    image       the content endpoint as before (D76): raster images keep their type for an <img>
    pdf         the app fetches the bytes from the content endpoint and hands them by
                postMessage to the PDF viewer, pdf.js on an opaque origin without network
                (frontend/src/viewer, served by api/frontend.py under /viewer/, D121)
    html        DOCX and ODT converted to sanitized HTML in a separate process with time and
                memory limits, cached on disk by SHA-256, shown in an iframe without scripts
                (GET /api/attachments/{id}/html, D122)
    audio/video the decoded bytes cached on disk by SHA-256, served with Range requests to the
                browser's media elements (GET /api/attachments/{id}/media, D123)

Nothing is converted in advance and nothing needs an import: the cache (MAILROBBE_PREVIEW_DIR,
D124) fills when someone opens a preview, and it can be deleted at any time.

The modules, besides kinds:

    convert     convert(): one conversion in a child process (python -I -m
                mailrobbe.preview.convert) with rlimits on memory, CPU time, file size and
                core dumps; ConversionFailed with the reason and whether it is worth remembering
    docx        docx_html(): DOCX through mammoth, after every XML part passed the safe parser
                of attachments/extract/packages.py; raster images as data: URLs
    odt         odt_html(): ODT by an own converter on the same safe parser
    sanitize    sanitize(): the allow list both converters' HTML goes through, page() wraps it
                in a document with its own CSP and stylesheet
    media       media_type(): audio and video recognised by their first bytes
    cache       PreviewCache: pages, remembered failures and media files per SHA-256 and
                version, written atomically; an unusable directory only costs the caching

The endpoints are in api/previews.py.
"""
