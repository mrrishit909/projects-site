"""FastAPI application factory (prefix /api/v1/invoicebridge)."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response

from . import commands, reads
from .errors import ApiError, detail, install_handlers
from .schemas import (ApproveRequest, AssignExceptionRequest, CommandResponse, CreditNoteRequest, ExportPayableRequest,
                      ExtensionRequest, FindDuplicatesRequest, ImportInvoiceRequest, Limit, MatchRequest, ReadResponse,
                      RejectRequest, ValidateInvoiceRequest)

PREFIX = "/api/v1/invoicebridge"
ROLES = commands.ROLES


def require_actor(request: Request, x_actor_id: str | None = Header(default=None),
                  x_actor_role: str | None = Header(default=None)) -> commands.Actor:
    """Commands need identity: no actor id is 401, a role other than clerk/reviewer/admin is 403."""
    request.state.request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
    if not x_actor_id or not x_actor_id.strip() or len(x_actor_id) > 128:
        raise ApiError(401, "UNAUTHENTICATED", "X-Actor-Id header is required",
                       [detail("header.X-Actor-Id", "ACTOR_REQUIRED", "missing or blank")])
    if x_actor_role not in ROLES:
        raise ApiError(403, "FORBIDDEN", "role must be clerk, reviewer or admin",
                       [detail("header.X-Actor-Role", "ROLE_FORBIDDEN", "role not permitted for commands")])
    return commands.Actor(x_actor_id.strip(), x_actor_role)


def _respond(result: tuple[dict[str, Any], bool], response: Response) -> dict[str, Any]:
    body, replayed = result
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return body


def create_app() -> FastAPI:
    app = FastAPI(title="InvoiceBridge API", version="1", docs_url=f"{PREFIX}/docs", openapi_url=f"{PREFIX}/openapi.json")
    install_handlers(app)
    router = APIRouter(prefix=PREFIX)

    def command(path: str, request_model: Any, handler: commands.Handler, on_replay: Any = None) -> None:
        name = path.rsplit("/", 1)[-1]

        def endpoint(body: Any, request: Request, response: Response,
                     actor: commands.Actor = Depends(require_actor)) -> dict[str, Any]:
            request.state.request_id = body.request_id
            return _respond(commands.execute(name, body, actor, handler, on_replay), response)

        endpoint.__annotations__["body"] = request_model  # the annotations are strings (PEP 563)
        router.add_api_route(path, endpoint, methods=["POST"], response_model=CommandResponse, tags=["commands"])

    command("/commands/import-invoice", ImportInvoiceRequest, commands.import_invoice)             # C01
    command("/commands/validate-invoice", ValidateInvoiceRequest, commands.validate_invoice_cmd)   # C02
    command("/commands/find-duplicates", FindDuplicatesRequest, commands.find_duplicates)          # C03
    command("/commands/match-three-way", MatchRequest, commands.match_three_way)                   # C04
    command("/commands/assign-exception", AssignExceptionRequest, commands.assign_exception)       # C05
    command("/commands/approve-invoice", ApproveRequest, commands.approve_invoice)                 # C07
    command("/commands/reject-invoice", RejectRequest, commands.reject_invoice)                    # C08
    command("/commands/export-payable", ExportPayableRequest, commands.export_payable, commands.export_replayed)   # C09
    command("/commands/apply-credit-note", CreditNoteRequest, commands.apply_credit_note)          # C10

    @router.post("/commands/correct-extraction", tags=["commands"])                                # C06: extension milestone
    def correct_extraction(body: ExtensionRequest, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        request.state.request_id = body.request_id
        raise commands.not_implemented("correct-extraction", "C06")

    @router.post("/commands/{action}", tags=["commands"], include_in_schema=False)
    def unsupported(action: str, request: Request, actor: commands.Actor = Depends(require_actor)) -> None:
        raise ApiError(404, "UNSUPPORTED_ACTION", f"unsupported action {action!r}",
                       [detail("action", "UNSUPPORTED_ACTION", "no such command")])

    @router.get("/data/invoices/{invoice_id}/audit", response_model=ReadResponse, tags=["reads"])
    @router.get("/data/invoices/{invoice_id}/lineage", response_model=ReadResponse, tags=["reads"])
    def read_audit(invoice_id: str) -> dict[str, Any]:
        return reads.read_invoice_audit(invoice_id)

    @router.get("/data/{entity}", response_model=ReadResponse, tags=["reads"])
    def read_data(entity: str, request: Request, limit: Limit = 50, cursor: str | None = None,
                  from_: str | None = Query(default=None, alias="from"), to: str | None = None) -> dict[str, Any]:
        filters = {k: v for k, v in request.query_params.items() if k not in reads.RESERVED}
        return reads.read_entity(entity, limit, cursor, from_, to, filters)

    @router.get("/metrics", response_model=ReadResponse, tags=["reads"])
    def read_metrics(from_: str | None = Query(default=None, alias="from"), to: str | None = None,
                     cutoff: str | None = None, group_by: str = "none") -> dict[str, Any]:
        return reads.read_metrics(from_, to, cutoff, group_by)

    app.include_router(router)
    return app
