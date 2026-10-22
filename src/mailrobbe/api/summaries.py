"""The summary of one mail or document (milestone 17, D307): GET /api/ai/summary, what the card
"KI-Zusammenfassung" shows. Models are in schemas.py (AiSummaryView).

Contract: the route is filled by the work on the summary card.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])
