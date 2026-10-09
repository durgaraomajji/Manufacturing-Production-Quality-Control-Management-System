"""FastAPI application entry point."""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import text

import app.models  # noqa: F401  (register all tables)
from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.rate_limit import RateLimitMiddleware
from app.db.base import Base
from app.db.init_db import seed_defaults
from app.db.session import SessionLocal, engine
from app.middleware.logging import RequestLoggingMiddleware
from app.utils.background_tasks import periodic_checks

logging.basicConfig(level=logging.DEBUG if settings.DEBUG else logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

TAGS = [
    {"name": "Authentication", "description": "Register, login (JWT + refresh), logout, password reset, current user"},
    {"name": "Users", "description": "User administration and activation"},
    {"name": "Plants & Production Lines", "description": "Levels 2-3"},
    {"name": "Products & BOM", "description": "Levels 4 and 6"},
    {"name": "Raw Materials", "description": "Level 5"},
    {"name": "Machines", "description": "Level 7"},
    {"name": "Production", "description": "Levels 8-11 and 17: orders, workflow, batches, workers, shifts"},
    {"name": "Quality", "description": "Levels 12-13: inspections and defects"},
    {"name": "Maintenance", "description": "Level 14"},
    {"name": "Downtime", "description": "Level 15"},
    {"name": "Inventory", "description": "Level 16"},
    {"name": "Dashboard & Reports", "description": "Levels 18-19"},
    {"name": "Audit & Notifications", "description": "Levels 20-21"},
    {"name": "Health", "description": "Liveness and database check"},
]


ERROR_SCHEMA = {
    "type": "object",
    "required": ["error"],
    "properties": {"error": {
        "type": "object",
        "required": ["code", "message"],
        "properties": {
            "code": {"type": "string", "examples": ["not_found"],
                     "description": "Machine-readable code: validation_error, unauthorized, forbidden, not_found, conflict, "
                                    "invalid_transition, insufficient_stock, business_rule_violation, rate_limited, internal_error"},
            "message": {"type": "string", "examples": ["Plant not found (id=7)"]},
            "details": {"description": "Optional structured details, e.g. per-field validation errors"},
        },
    }},
}


def _error_ref(description: str) -> dict:
    return {"description": description, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}


def build_openapi(application: FastAPI) -> dict:
    """OpenAPI document matching the real error envelope ({"error": {...}}) rather than FastAPI's default
    {"detail": [...]}, and documenting the common 401 / 403 / 404 / 409 / 429 responses."""
    if application.openapi_schema:
        return application.openapi_schema
    schema = get_openapi(title=application.title, version=application.version, description=application.description,
                         routes=application.routes, tags=application.openapi_tags)
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components["ErrorResponse"] = ERROR_SCHEMA
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)
    for path, item in schema["paths"].items():
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            responses = op.setdefault("responses", {})
            if "422" in responses:
                responses["422"] = _error_ref("Validation error or business-rule violation")
            if op.get("security"):
                responses.setdefault("401", _error_ref("Missing, invalid, expired or revoked token"))
                responses.setdefault("403", _error_ref("Role lacks the required permission, or account deactivated"))
            if "{" in path:
                responses.setdefault("404", _error_ref("Resource not found"))
            if method in ("post", "put", "patch", "delete") and op.get("security"):
                responses.setdefault("409", _error_ref("Conflict, invalid status transition or insufficient stock"))
            if path.startswith(settings.API_V1_PREFIX + "/auth/") and not op.get("security"):
                responses.setdefault("429", _error_ref("Too many attempts"))
    application.openapi_schema = schema
    return schema


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        try:
            seed_defaults(db)
        except Exception:
            logger.exception("Could not seed defaults (have the migrations been applied?)")
    task = None
    if settings.ENABLE_BACKGROUND_CHECKS:
        task = asyncio.create_task(periodic_checks(settings.BACKGROUND_CHECK_INTERVAL_SECONDS))
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME, version=settings.APP_VERSION, openapi_tags=TAGS, lifespan=lifespan,
        description="Production-oriented backend for managing plants, production lines, products, BOMs, materials, machines, "
                    "production orders, batches, quality control, maintenance, inventory and analytics.",
        docs_url="/docs", redoc_url="/redoc",
    )
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins_list, allow_credentials=False,
        allow_methods=["*"], allow_headers=["*"])
    register_exception_handlers(application)
    application.openapi = lambda: build_openapi(application)
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/docs")

    @application.get("/health", tags=["Health"], summary="Liveness + database check")
    def health():
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "version": settings.APP_VERSION, "environment": settings.ENVIRONMENT}

    return application


app = create_app()
