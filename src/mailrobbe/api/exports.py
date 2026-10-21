"""Exports of mails for lawyers and archives (milestone 8, D62, D63): the PDF of one mail, and
ZIP exports of a selection with EML, PDF and manifest, recorded in mail_export.

Registered before the detail router, so /api/mails/{id}/pdf stays with this module.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["exports"])
