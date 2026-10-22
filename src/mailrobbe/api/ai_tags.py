"""AI tags and theme hints in the lists (milestone 17, D309, D310): GET /api/ai/facets, GET
/api/ai/tags and POST /api/ai/tags/{id}/adopt. Models are in schemas.py (AiFacets, AiTagCount,
AiTagAdopt, AiTagAdopted); the filters ai_tag and ai_theme are in filters.py.

Contract: the routes are filled by the work on the lists.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/ai", tags=["ai"])
