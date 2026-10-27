"""FastAPI application factory (prefix /api/v1/pipeline-observatory)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (ArchiveEvidenceRequest, CommandResponse, CommitBatchRequest, FetchSourcePageRequest, InjectFaultRequest, Limit,
                      PublishSnapshotRequest, ReadResponse, RecoverIncidentRequest, RequestBackfillRequest, RunQualityGateRequest,
                      TransformModelsRequest, ValidateContractRequest)

PREFIX = "/api/v1/pipeline-observatory"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None), x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than engineer/operator/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required", [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be engineer, operator or admin", [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def actor_for(roles: frozenset[str], name: str):
    """The actor dependency of one command: identity first (401), then the role inventory (403), both before the body is read."""
    def dep(actor: commands.Actor = Depends(require_actor)) -> commands.Actor:
        commands._need_role(actor, roles, name)
        return actor
    return dep


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="Pipeline Observatory API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    def command(path: str, request_model: Any, handler: commands.Handler, roles: frozenset[str]) -> None:
        name = path.rsplit("/", 1)[-1]

        def endpoint(body: Any, request: Request, response: Response, actor: commands.Actor = Depends(actor_for(roles, name))) -> dict[str, Any]:
            request.state.request_id = body.request_id
            return _respond(commands.execute(name, body, actor, handler, roles), response)

        endpoint.__annotations__["body"] = request_model  # the annotations are strings (PEP 563)
        router.add_api_route(path, endpoint, methods=["POST"], response_model=CommandResponse, tags=["commands"])

    everyone, operators = commands.ALL_ROLES, commands.OPERATOR_ROLES
    command("/commands/fetch-source-page", FetchSourcePageRequest, commands.fetch_source_page, everyone)      # C01
    command("/commands/validate-contract", ValidateContractRequest, commands.validate_contract, everyone)     # C02
    command("/commands/commit-batch", CommitBatchRequest, commands.commit_batch, everyone)                    # C03
    command("/commands/transform-models", TransformModelsRequest, commands.transform_models, everyone)        # C04
    command("/commands/run-quality-gate", RunQualityGateRequest, commands.run_quality_gate, everyone)         # C05
    command("/commands/publish-snapshot", PublishSnapshotRequest, commands.publish_snapshot, operators)       # C06
    command("/commands/inject-fault", InjectFaultRequest, commands.inject_fault, operators)                   # C07
    command("/commands/request-backfill", RequestBackfillRequest, commands.request_backfill, everyone)        # C08
    command("/commands/recover-incident", RecoverIncidentRequest, commands.recover_incident, operators)       # C09
    command("/commands/archive-evidence", ArchiveEvidenceRequest, commands.archive_evidence, operators)       # C10

    @router.post("/commands/{action}", tags=["commands"], include_in_schema=False)
    def unsupported(action: str, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        raise ApiError(404, "UNSUPPORTED_ACTION", f"unsupported action {action!r}", [detail("action", "UNSUPPORTED_ACTION", "no such command")])

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, request: Request, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"), to: str | None = None) -> dict[str, Any]:
        filters = {k: v for k, v in request.query_params.items() if k not in reads.RESERVED}
        return reads.read_entity(entity, limit, cursor, from_, to, filters)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"), to: str | None = None, cutoff: str | None = None,
                     source_id: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(from_, to, cutoff, source_id, group_by)

    app.include_router(router)
    return app


app = create_app()
