"""Error envelope (docs/api-contract.md): ``{error: {code, message, details}, request_id}``.

No stack traces, tokens or connection strings ever reach a response body.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from trustledger.errors import DomainError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("trustledger.api")


class ApiError(Exception):
    """A business or protocol error with an HTTP status and a stable ``code``."""

    def __init__(self, status: int, code: str, message: str,
                 details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


def detail(path: str, rule_id: str, message: str) -> dict[str, Any]:
    return {"path": path, "rule_id": rule_id, "message": message}


#: Domain reason code -> (HTTP status, error.code). Anything else is a 422 VALIDATION_FAILED.
_STATUS_BY_REASON: dict[str, tuple[int, str]] = {
    "INVALID_STATE": (409, "INVALID_STATE"),
}


def from_domain(err: DomainError, path: str) -> ApiError:
    """Map a DomainError to an ApiError whose ``details[].rule_id`` is the reason code (422 unless listed above)."""
    status, code = _STATUS_BY_REASON.get(err.code, (422, "VALIDATION_FAILED"))
    item: dict[str, Any] = detail(err.path or path, err.code, err.message)
    if err.details:
        item["context"] = err.details
    return ApiError(status, code, err.message, [item])


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:16]}"


def error_response(status: int, code: str, message: str, request_id: str,
                   details: list[dict[str, Any]] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={
        "error": {"code": code, "message": message, "details": details or []},
        "request_id": request_id})


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


_RULE_BY_PYDANTIC = {"missing": "FIELD_REQUIRED", "extra_forbidden": "FIELD_UNEXPECTED",
                     "json_invalid": "BODY_INVALID_JSON"}


def install_handlers(app: FastAPI) -> None:
    """Register handlers that turn every failure into the error envelope."""

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, _request_id(request), exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        body = exc.body if isinstance(exc.body, dict) else {}
        rid = body.get("request_id")
        request_id = rid if isinstance(rid, str) and 0 < len(rid) <= 128 else _request_id(request)
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err["loc"] if p != "body"]
            kind = str(err["type"])
            rule = _RULE_BY_PYDANTIC.get(kind) or (kind if kind.isupper() else "FIELD_INVALID")
            path = "body" if kind == "json_invalid" else ".".join(loc)
            details.append(detail(path, rule, str(err.get("msg", "invalid"))))
        return error_response(422, "VALIDATION_FAILED", "request validation failed",
                              request_id, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 401: "UNAUTHENTICATED",
                 403: "FORBIDDEN"}
        message = {404: "no such route or resource", 405: "method not allowed"}.get(
            exc.status_code, str(exc.detail))
        resp = error_response(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"),
                              message, _request_id(request))
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(psycopg.errors.DataError)
    async def _data_error(request: Request, exc: psycopg.errors.DataError) -> JSONResponse:
        log.warning("data error: %s", exc.sqlstate)
        return error_response(422, "VALIDATION_FAILED", "a value is out of range for storage",
                              _request_id(request),
                              [detail("input", "VALUE_OUT_OF_RANGE", "a value does not fit its column")])

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the type only: messages from the driver can carry connection details.
        log.error("unhandled %s on %s", type(exc).__name__, request.url.path)
        return error_response(500, "INTERNAL_ERROR", "internal error", _request_id(request))

