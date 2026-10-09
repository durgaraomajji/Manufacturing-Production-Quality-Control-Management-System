"""Domain exceptions and global exception handlers.

Every error response has the same shape:
    {"error": {"code": "...", "message": "...", "details": ...}}
"""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str = "", *, details: Any = None, headers: dict | None = None):
        super().__init__(message)
        self.message = message or self.__class__.__name__
        self.details = details
        self.headers = headers


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"

    def __init__(self, entity: str = "Resource", identifier: Any = None):
        suffix = f" (id={identifier})" if identifier is not None else ""
        super().__init__(f"{entity} not found{suffix}")


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class InvalidTransitionError(AppError):
    status_code = 409
    code = "invalid_transition"


class InsufficientStockError(AppError):
    status_code = 409
    code = "insufficient_stock"


class BusinessRuleError(AppError):
    status_code = 422
    code = "business_rule_violation"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"

    def __init__(self, message: str = "Could not validate credentials", **kw):
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"}, **kw)


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


def _body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(_body("validation_error", "Request validation failed", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(IntegrityError)
    async def integrity_handler(_: Request, exc: IntegrityError):
        logger.warning("Integrity error: %s", exc.orig)
        return JSONResponse(_body("integrity_error", "The operation violates a database constraint (duplicate or referenced record)"), status_code=409)

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(_body("internal_error", "Internal server error"), status_code=500)
