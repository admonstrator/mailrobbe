"""The mail list: search, filters, keyset pages, counts, neighbours, CSV export (D19 to D21, D25).

Routes: GET /api/mails, /api/mails/summary, /api/mails/export.csv, /api/mails/{id}/neighbors.
Registered before the detail router, so /api/mails/summary is not taken for a mail id.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["mails"])
