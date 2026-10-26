"""FastAPI application factory (prefix /api/v1/revenue-atlas)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import CommandResponse, IngestRequest, Limit, ReadResponse, ReturnRequest, ShipmentRequest

PREFIX = "/api/v1/revenue-atlas"
ROLES = frozenset({"analyst", "steward"})


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than analyst/steward is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be analyst or steward",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="Revenue Atlas API", version="1", docs_url=f"{PREFIX}/docs",
                  openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    @router.post("/commands/ingest-sales", response_model=CommandResponse, tags=["commands"])
    def c01(body: IngestRequest, request: Request, response: Response,
            actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
        request.state.request_id = body.request_id
        return _respond(commands.run_ingest(body, actor), response)

    @router.post("/commands/resolve-historical-cost", response_model=CommandResponse, tags=["commands"])
    def c02(body: ShipmentRequest, request: Request, response: Response,
            actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
        request.state.request_id = body.request_id
        return _respond(commands.run_resolve_cost(body, actor), response)

    @router.post("/commands/post-a-partial-return", response_model=CommandResponse, tags=["commands"])
    def c03(body: ReturnRequest, request: Request, response: Response,
            actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
        request.state.request_id = body.request_id
        return _respond(commands.run_return(body, actor), response)

    @router.post("/commands/allocate-freight", response_model=CommandResponse, tags=["commands"])
    def c04(body: ShipmentRequest, request: Request, response: Response,
            actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
        request.state.request_id = body.request_id
        return _respond(commands.run_allocate_freight(body, actor), response)

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"),
                  to: str | None = None) -> dict[str, Any]:
        return reads.read_entity(entity, limit, cursor, from_, to)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"),
                     to: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(from_, to, group_by)

    app.include_router(router)
    return app
