"""Places (milestone 20, D247, D248): photos with a position, the places named in the mails and
the places of invitations, under the map's filters (schemas.PlaceParams)."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["places"])
