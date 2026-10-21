"""The research file (milestone 8, D53 to D61): marks, notes, tags, Akten, saved searches, bulk
changes and permalinks. The routes are listed in schemas.py.

Registered before the detail router, so /api/mails/bulk is not taken for a mail id.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["research"])
