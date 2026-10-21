"""One mail: metadata, bodies read on demand from its MBOX file, EML download, DKIM recheck and
note (D22, D23).

Routes: GET /api/mails/{id}, /api/mails/{id}/body, /api/mails/{id}/eml,
POST /api/mails/{id}/dkim/recheck, PUT /api/mails/{id}/note.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["mail"])
