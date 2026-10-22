"""Hide rules (milestone 18, D221 to D223): the rules, their preview and suggestions. Routes:
GET, POST /api/hide-rules, POST /api/hide-rules/preview, GET /api/hide-rules/suggestions,
PUT and DELETE /api/hide-rules/{id}. Contract stub: milestone 18 fills it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["hiding"])
