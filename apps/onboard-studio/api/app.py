"""FastAPI application factory (prefix /api/v1/onboard-studio)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (AcceptRequest, ApproveRequest, CommandResponse, CompleteRequest, CreateCaseRequest,
                      DocumentRequest, ExtensionRequest, Limit, PauseRequest, PublishRequest, ReadResponse,
                      RejectRequest, ReopenRequest, UnlockRequest)

PREFIX = "/api/v1/onboard-studio"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than ops/reviewer/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be ops, reviewer or admin",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="Onboard Studio API", version="1", docs_url=f"{PREFIX}/docs",
                  openapi_url=f"{PREFIX}/openapi.json")
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

    command("/commands/create-case", CreateCaseRequest, commands.create_case)                      # C01
    command("/commands/submit-document", DocumentRequest, commands.submit_document)                # C02
    command("/commands/reject-submission", RejectRequest, commands.reject_submission)              # C03
    command("/commands/resubmit-document", DocumentRequest, commands.resubmit_document)            # C04
    command("/commands/unlock-dependent-step", UnlockRequest, commands.unlock_step)                # C05
    command("/commands/approve-step", ApproveRequest, commands.approve_step)                       # C06
    command("/commands/pause-sla", PauseRequest, commands.pause_sla)                               # C08
    command("/commands/complete-case", CompleteRequest, commands.complete_case)                    # C09
    command("/commands/publish-workflow-version", PublishRequest, commands.publish_workflow_version)  # P
    command("/commands/accept-document", AcceptRequest, commands.accept_document)                  # addition

    def refuse(path: str, label: str) -> None:
        def endpoint(body: ExtensionRequest, request: Request,
                     actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
            request.state.request_id = body.request_id
            raise commands.not_implemented(path.rsplit("/", 1)[-1], label)

        router.add_api_route(path, endpoint, methods=["POST"], tags=["commands"], include_in_schema=True)

    refuse("/commands/reassign-work", "C07")        # extension milestone
    refuse("/commands/migrate-workflow", "C10")     # extension milestone

    @router.post("/commands/reopen-case", tags=["commands"])
    def reopen(body: ReopenRequest, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        request.state.request_id = body.request_id
        commands.reopen_case(body.input.case_id)

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
                     cutoff: str | None = None, state: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(from_, to, cutoff, state, group_by)

    app.include_router(router)
    return app
