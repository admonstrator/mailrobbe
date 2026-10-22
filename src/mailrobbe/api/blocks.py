"""Standard blocks (milestone 18, D224 to D227): their list, figures, pages and the team's
choices. Routes: GET /api/blocks/summary, GET /api/blocks, GET /api/blocks/{hash},
PUT /api/blocks/{hash}/override. Contract stub: milestone 18 fills it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["blocks"])
