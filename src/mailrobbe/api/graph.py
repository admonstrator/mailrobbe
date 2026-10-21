"""The relationship map: the excerpt, its size and its GraphML download (D37, D38).

Routes: GET /api/graph, /api/graph/size, /api/graph/export.graphml. All three take GraphParams
and compute the excerpt with graph/excerpt.py, from the edge aggregation alone; the download is
the same excerpt as /api/graph, so it is refused above MAX_GRAPH_NODES as well.

The excerpt's queries run without JIT compilation: PostgreSQL compiles those that touch the
larger part of the edge table, which costs more than it saves at a few hundred milliseconds.
"""

from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import Session, api_error
from mailrobbe.api.schemas import Graph, GraphParams, GraphSize
from mailrobbe.graph import excerpt, graphml

router = APIRouter(prefix="/api", tags=["graph"])

GRAPHML_FILENAME = "mailrobbe-karte.graphml"
_PIECE = 64 * 1024  # characters per piece of the download; graphml_chunks yields one element
_NO_JIT = select(func.set_config("jit", "off", True))  # for the request's transaction


@contextmanager
def _errors() -> Iterator[None]:
    """The excerpt's exceptions as the contract's error responses."""
    try:
        yield
    except excerpt.ExcerptError as error:
        raise api_error(400, "invalid_filter", str(error)) from error
    except excerpt.UnknownCenter as error:
        raise api_error(404, "not_found", str(error)) from error
    except excerpt.GraphTooLarge as error:
        raise api_error(400, "graph_too_large", str(error)) from error


@router.get("/graph")
async def graph(params: Annotated[GraphParams, Query()], session: Session) -> Graph:
    return await _graph(session, params)


@router.get("/graph/size")
async def size(params: Annotated[GraphParams, Query()], session: Session) -> GraphSize:
    await session.execute(_NO_JIT)
    with _errors():
        return await excerpt.graph_size(session, params)


@router.get("/graph/export.graphml")
async def export_graphml(
    params: Annotated[GraphParams, Query()], session: Session
) -> StreamingResponse:
    shown = await _graph(session, params)
    nodes = (
        graphml.GraphmlNode(
            id=node.id,
            label=node.name or node.email,
            email=node.email,
            domain=node.domain,
            kind=None if node.kind is None else node.kind.value,
            mails=node.mails,
        )
        for node in shown.nodes
    )
    edges = (
        graphml.GraphmlEdge(
            source=edge.source,
            target=edge.target,
            weight=edge.weight,
            a_to_b=edge.a_to_b,
            b_to_a=edge.b_to_a,
            cc=edge.cc,
        )
        for edge in shown.edges
    )
    return StreamingResponse(
        _pieces(graphml.graphml_chunks(nodes, edges)),
        media_type=graphml.MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{GRAPHML_FILENAME}"'},
    )


async def _graph(session: AsyncSession, params: GraphParams) -> Graph:
    await session.execute(_NO_JIT)
    with _errors():
        return await excerpt.build_graph(session, params)


async def _pieces(chunks: Iterable[str]) -> AsyncIterator[bytes]:
    """The chunks joined into pieces of about _PIECE characters, one send each."""
    piece: list[str] = []
    length = 0
    for chunk in chunks:
        piece.append(chunk)
        length += len(chunk)
        if length >= _PIECE:
            yield "".join(piece).encode()
            piece, length = [], 0
    yield "".join(piece).encode()
