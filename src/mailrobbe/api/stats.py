"""Whole-archive figures and the MBOX file list: GET /api/stats, /api/stats/sender-domains,
/api/mbox-files (D19)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["stats"])
