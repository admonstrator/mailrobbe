"""Persons: the person list, profiles, contacts, mail counts, alias suggestions and merges
(milestone 5, D28 to D33). Endpoints and models are in schemas.py.

Static paths (/api/persons/suggestions, /api/persons/merge) are registered before the ones
with a person id.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["persons"])
