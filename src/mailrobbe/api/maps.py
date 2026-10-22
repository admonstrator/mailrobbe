"""Maps (milestone 20, D244 to D246): the overview map's town labels and the detail map, its
download as a run of `mailrobbe map download` and its PMTiles file."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["maps"])
