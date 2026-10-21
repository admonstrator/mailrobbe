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
"""
