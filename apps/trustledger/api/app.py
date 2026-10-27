"""FastAPI application factory (prefix /api/v1/trustledger)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (ApproveMergeRequest, CommandResponse, CorrectDatasetRowsRequest, DisableRuleRequest, Limit, OpenIssueRequest,
                      PublishDefinitionRequest, ReadResponse, RecordRefreshRequest, RegisterDatasetRequest, ReverseMergeRequest,
                      RunRuleRequest, SuggestMatchRequest, TriageIssueRequest, VerifyRemediationRequest)

PREFIX = "/api/v1/trustledger"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None), x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need a registered, active actor (D-10 R7-03). ``X-Actor-Id`` is resolved EXACTLY against the owners register: no id is 401
    ACTOR_REQUIRED, an id that is not registered is 401 UNKNOWN_ACTOR, an inactive owner is 403 ACTOR_INACTIVE. The role comes from the
    register; ``X-Actor-Role`` must be one of analyst/steward/admin (else 403 ROLE_FORBIDDEN) and must equal the register's role (else
    403 ROLE_MISMATCH). Nobody can claim a role they do not hold, and nobody unregistered can decide anything."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required", [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be analyst, steward or admin", [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.resolve_actor(x_actor_id, x_actor_role)


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
    app = FastAPI(title="TrustLedger API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    def command(path: str, request_model: Any, handler: commands.Handler, roles: frozenset[str]) -> None:
        name = path.rsplit("/", 1)[-1]

        def endpoint(body: Any, request: Request, response: Response, actor: commands.Actor = Depends(actor_for(roles, name))) -> dict[str, Any]:
            request.state.request_id = body.request_id
            return _respond(commands.execute(name, body, actor, handler, roles), response)

        endpoint.__annotations__["body"] = request_model  # the annotations are strings (PEP 563)
        router.add_api_route(path, endpoint, methods=["POST"], response_model=CommandResponse, tags=["commands"])

    everyone, stewards = commands.ALL_ROLES, commands.STEWARD_ROLES
    command("/commands/register-dataset", RegisterDatasetRequest, commands.register_dataset, everyone)        # C01
    command("/commands/publish-definition", PublishDefinitionRequest, commands.publish_definition, stewards)  # C02
    command("/commands/run-rule", RunRuleRequest, commands.run_rule, everyone)                                # C03
    command("/commands/open-issue", OpenIssueRequest, commands.open_issue, everyone)                          # C04
    command("/commands/triage-issue", TriageIssueRequest, commands.triage_issue, everyone)                    # C05
    command("/commands/suggest-match", SuggestMatchRequest, commands.suggest_match, everyone)                 # C06
    command("/commands/approve-merge", ApproveMergeRequest, commands.approve_merge, stewards)                 # C07
    command("/commands/reverse-merge", ReverseMergeRequest, commands.reverse_merge, stewards)                 # C08
    command("/commands/disable-rule", DisableRuleRequest, commands.disable_rule, stewards)                    # C09
    command("/commands/verify-remediation", VerifyRemediationRequest, commands.verify_remediation, stewards)  # C10
    command("/commands/correct-dataset-rows", CorrectDatasetRowsRequest, commands.correct_dataset_rows, everyone)  # C11
    command("/commands/record-refresh", RecordRefreshRequest, commands.record_refresh, everyone)               # C12

    @router.post("/commands/{action}", tags=["commands"], include_in_schema=False)
    def unsupported(action: str, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        raise ApiError(404, "UNSUPPORTED_ACTION", f"unsupported action {action!r}", [detail("action", "UNSUPPORTED_ACTION", "no such command")])

    @router.get("/data/comparable_runs", response_model=ReadResponse, tags=["reads"])
    def read_comparable(rule_id: str | None = None) -> dict[str, Any]:
        return reads.read_comparable_runs(rule_id)

    @router.get("/data/identity_map", response_model=ReadResponse, tags=["reads"])
    def read_identity(as_of: str | None = None) -> dict[str, Any]:
        return reads.read_identity_map(as_of)

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, request: Request, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"), to: str | None = None) -> dict[str, Any]:
        filters = {k: v for k, v in request.query_params.items() if k not in reads.RESERVED}
        return reads.read_entity(entity, limit, cursor, from_, to, filters)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"), to: str | None = None, as_of: str | None = None,
                     dataset_id: str | None = None, weight_version: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(from_, to, as_of, dataset_id, weight_version, group_by)

    app.include_router(router)
    return app
