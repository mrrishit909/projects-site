"""FastAPI application factory (prefix /api/v1/productsignal)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (AnalyzeRequest, AssignExperimentRequest, CheckMaturityRequest, CommandResponse, DefineFunnelRequest,
                      FreezePlanRequest, Limit, ReadResponse, RecordDecisionRequest, RecordExposureRequest,
                      ResolveIdentityRequest, ReviewGuardrailsRequest, ValidateTrackingRequest)

PREFIX = "/api/v1/productsignal"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than analyst/experimenter/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be analyst, experimenter or admin",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
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
    app = FastAPI(title="ProductSignal API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    def command(path: str, request_model: Any, handler: commands.Handler, roles: frozenset[str]) -> None:
        name = path.rsplit("/", 1)[-1]

        def endpoint(body: Any, request: Request, response: Response,
                     actor: commands.Actor = Depends(actor_for(roles, name))) -> dict[str, Any]:
            request.state.request_id = body.request_id
            return _respond(commands.execute(name, body, actor, handler, roles), response)

        endpoint.__annotations__["body"] = request_model  # the annotations are strings (PEP 563)
        router.add_api_route(path, endpoint, methods=["POST"], response_model=CommandResponse, tags=["commands"])

    everyone, designers = commands.ALL_ROLES, commands.DESIGN_ROLES
    command("/commands/validate-tracking", ValidateTrackingRequest, commands.validate_tracking, everyone)           # C01
    command("/commands/resolve-identity", ResolveIdentityRequest, commands.resolve_identity, everyone)              # C02
    command("/commands/define-funnel", DefineFunnelRequest, commands.define_funnel, everyone)                       # C03
    command("/commands/assign-experiment", AssignExperimentRequest, commands.assign_experiment, designers)          # C04
    command("/commands/record-exposure", RecordExposureRequest, commands.record_exposure, designers)                # C05
    command("/commands/freeze-analysis-plan", FreezePlanRequest, commands.freeze_analysis_plan, designers)          # C06
    command("/commands/check-maturity", CheckMaturityRequest, commands.check_maturity, everyone)                    # C07
    command("/commands/analyze-experiment", AnalyzeRequest, commands.analyze_experiment, everyone)                  # C08
    command("/commands/review-guardrails", ReviewGuardrailsRequest, commands.review_guardrails, everyone)           # C09
    command("/commands/record-decision", RecordDecisionRequest, commands.record_decision, designers)                # C10

    @router.post("/commands/{action}", tags=["commands"], include_in_schema=False)
    def unsupported(action: str, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        raise ApiError(404, "UNSUPPORTED_ACTION", f"unsupported action {action!r}",
                       [detail("action", "UNSUPPORTED_ACTION", "no such command")])

    @router.get("/data/analysis_runs/{analysis_id}", response_model=ReadResponse, tags=["reads"])
    def read_run(analysis_id: str) -> dict[str, Any]:
        return reads.read_analysis_run(analysis_id)

    @router.get("/data/experiment_versions/{xv}/audit", response_model=ReadResponse, tags=["reads"])
    def read_audit(xv: str) -> dict[str, Any]:
        return reads.read_experiment_audit(xv)

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, request: Request, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"), to: str | None = None) -> dict[str, Any]:
        filters = {k: v for k, v in request.query_params.items() if k not in reads.RESERVED}
        return reads.read_entity(entity, limit, cursor, from_, to, filters)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"), to: str | None = None, cutoff: str | None = None,
                     experiment_version_id: str | None = None, group_by: str = "none",
                     analysis_id: str | None = None) -> dict[str, Any]:
        return reads.read_metrics(from_, to, cutoff, experiment_version_id, group_by, analysis_id)

    app.include_router(router)
    return app
