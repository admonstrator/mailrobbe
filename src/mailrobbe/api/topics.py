"""Topics: terms that stand out per period, in a selection, and clusters of terms (milestone 13,
D140 to D148). Models are in schemas.py. Routes: GET /api/topics/periods, /api/topics/terms,
/api/topics/clusters.

Contract stub: every route answers as before the first topics phase (no state, empty lists).
"""

from typing import Annotated

from fastapi import APIRouter, Query

from mailrobbe.api.deps import Session
from mailrobbe.api.schemas import (
    TopicClusters,
    TopicPeriodParams,
    TopicPeriods,
    TopicState,
    TopicTermParams,
    TopicTerms,
)

router = APIRouter(prefix="/api/topics", tags=["topics"])

_NOTHING = TopicState(computed_at=None, mails=0, terms=0, clusters=0)


@router.get("/periods")
async def periods(params: Annotated[TopicPeriodParams, Query()], session: Session) -> TopicPeriods:
    return TopicPeriods(state=_NOTHING, unit=params.unit, periods=[])


@router.get("/terms")
async def terms(params: Annotated[TopicTermParams, Query()], session: Session) -> TopicTerms:
    return TopicTerms(
        state=_NOTHING, mails=None, counted=0, sampled=False, terms=[], common=[], timed_out=False
    )


@router.get("/clusters")
async def clusters(session: Session) -> TopicClusters:
    return TopicClusters(state=_NOTHING, clusters=[])
