"""FastAPI application factory (prefix /api/v1/serviceflow)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (AssignQueueRequest, CommandResponse, ComparePoliciesRequest, ExtensionRequest, IngestRequest,
                      Limit, PauseRequest, ReadResponse, ReopenRequest, ResolveRequest, ResumeRequest,
                      RunSimulationRequest, StartServiceRequest, TransferRequest)

PREFIX = "/api/v1/serviceflow"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than analyst/supervisor/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be analyst, supervisor or admin",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="ServiceFlow API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    def command(path: str, request_model: Any, handler: commands.Handler) -> None:
        name = path.rsplit("/", 1)[-1]

        def endpoint(body: Any, request: Request, response: Response,
                     actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
            request.state.request_id = body.request_id
            return _respond(commands.execute(name, body, actor, handler), response)

        endpoint.__annotations__["body"] = request_model  # the annotations are strings (PEP 563)
        router.add_api_route(path, endpoint, methods=["POST"], response_model=CommandResponse, tags=["commands"])

    command("/commands/ingest-ticket-events", IngestRequest, commands.ingest_ticket_events)   # C01
    command("/commands/assign-queue", AssignQueueRequest, commands.assign_queue)              # C02
    command("/commands/start-service", StartServiceRequest, commands.start_service)           # C03
    command("/commands/transfer-ticket", TransferRequest, commands.transfer_ticket)           # C04
    command("/commands/pause-work", PauseRequest, commands.pause_work)                        # C05
    command("/commands/resume-work", ResumeRequest, commands.resume_work)                     # C05 (resume)
    command("/commands/reopen-ticket", ReopenRequest, commands.reopen_ticket)                 # C06
    command("/commands/resolve-ticket", ResolveRequest, commands.resolve_ticket)              # addition
    command("/commands/run-simulation", RunSimulationRequest, commands.run_simulation)        # C08
    command("/commands/compare-policies", ComparePoliciesRequest, commands.compare_policies)  # C09

    def refuse(path: str, label: str) -> None:
        def endpoint(body: ExtensionRequest, request: Request,
                     actor: commands.Actor = Depends(require_actor)) -> None:
            request.state.request_id = body.request_id
            raise commands.not_implemented(path.rsplit("/", 1)[-1], label)

        router.add_api_route(path, endpoint, methods=["POST"], tags=["commands"], include_in_schema=True)

    refuse("/commands/build-shift-scenario", "C07")     # extension milestone
    refuse("/commands/export-recommendation", "C10")    # extension milestone

    @router.post("/commands/{action}", tags=["commands"], include_in_schema=False)
    def unsupported(action: str, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        raise ApiError(404, "UNSUPPORTED_ACTION", f"unsupported action {action!r}",
                       [detail("action", "UNSUPPORTED_ACTION", "no such command")])

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, request: Request, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"), to: str | None = None) -> dict[str, Any]:
        filters = {k: v for k, v in request.query_params.items() if k not in reads.RESERVED}
        return reads.read_entity(entity, limit, cursor, from_, to, filters)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"), to: str | None = None,
                     cutoff: str | None = None, group_by: str = "none",
                     abandonable_channels: str | None = None) -> dict[str, Any]:
        return reads.read_metrics(from_, to, cutoff, group_by, abandonable_channels)

    app.include_router(router)
    return app
