"""FastAPI application factory (prefix /api/v1/supplyscope)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (ArrivalRequest, CommandResponse, CompareRequest, ExportRequest, ExtensionRequest, ForecastRequest,
                      Limit, LoadMovementsRequest, ReadResponse, ReconstructRequest, ReplenishRequest,
                      ReviewSupplierRequest, UnmetRequest)

PREFIX = "/api/v1/supplyscope"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than planner/buyer/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be planner, buyer or admin",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="SupplyScope API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
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

    command("/commands/load-movements", LoadMovementsRequest, commands.load_movements)                      # C01
    command("/commands/reconstruct-stock", ReconstructRequest, commands.reconstruct_stock)                  # C02
    command("/commands/forecast-demand", ForecastRequest, commands.forecast_demand_command)                 # C03
    command("/commands/calculate-replenishment", ReplenishRequest, commands.calculate_replenishment)        # C05
    command("/commands/simulate-arrival", ArrivalRequest, commands.simulate_arrival)                        # C06
    command("/commands/record-unmet-demand", UnmetRequest, commands.record_unmet_demand)                    # C07
    command("/commands/compare-policies", CompareRequest, commands.compare_policies_command)                # C08
    command("/commands/review-supplier", ReviewSupplierRequest, commands.review_supplier)                   # C09
    command("/commands/export-buying-plan", ExportRequest, commands.export_buying_plan)                     # C10

    @router.post("/commands/classify-skus", tags=["commands"])                                              # C04
    def classify_skus(body: ExtensionRequest, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        request.state.request_id = body.request_id
        raise commands.not_implemented("classify-skus", "C04")

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
    def read_metrics(as_of: str | None = None, from_: str | None = Query(default=None, alias="from"),
                     to: str | None = None, state: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(as_of, from_, to, state, group_by)

    app.include_router(router)
    return app
