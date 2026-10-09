# Manufacturing Production & Quality Control Management System

FastAPI backend covering Levels 1–23 of the assignment: auth and RBAC, plants and lines, products and BOM, materials,
machines, production orders and batches, workers and shifts, inspections and defects, maintenance and downtime,
inventory, approval workflow, dashboard and reports, audit logs, notifications, security, tests and Docker.

## Stack
Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, PostgreSQL (MySQL works via the URL), JWT (PyJWT), Alembic, Pytest, Docker.

## Quick start (local, SQLite)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
- Swagger UI: http://localhost:8000/docs  ·  ReDoc: /redoc  ·  OpenAPI: /openapi.json  ·  Health: /health
- API prefix: `/api/v1`
- On first start the three shifts and a super admin are seeded:
  **admin@example.com / Admin@12345** (change via `FIRST_SUPERUSER_*` in `.env`).
- In Swagger click **Authorize** and log in with the email as username and the password.

## Docker (PostgreSQL)
```bash
cp .env.example .env
docker compose up --build
```
The container runs `alembic upgrade head` and then starts uvicorn on port 8000.

## Migrations
```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
alembic downgrade -1
```
Set `AUTO_CREATE_TABLES=false` when Alembic manages the schema (the compose file does this).

## Tests
```bash
pytest                      # 198 tests, in-memory SQLite, fresh schema per test
pytest tests/integration/test_e2e_flow.py
```
`test_e2e_flow.py` runs the full mandatory flow: login → plant → line → product → BOM → materials → machine → order →
availability check → workers → batch → output → inspection → defects → completion → inventory → maintenance →
dashboard → reports → audit-log verification.

## Layout
```
app/
  api/v1 routers     HTTP layer, permission checks, one commit per request
  services/          business rules (state machines, stock, approvals)
  repositories/      data access
  models/ schemas/   SQLAlchemy tables / Pydantic models
  core/              config, security, permissions, rate limiting, errors
  db/                session, seed, Alembic migrations
tests/               unit/ and integration/
```

## Roles
super_admin (all), plant_manager, production_manager, quality_manager, maintenance_engineer, store_manager,
production_supervisor, worker. The permission matrix lives in `app/core/permissions.py`.

## Design notes
- **One transaction per request**: services flush, routers commit; any error rolls everything back.
- **Inventory**: all stock changes go through one service, never go negative, and write an immutable ledger row plus an audit entry.
- **Materials are issued when a batch starts** (BOM × planned quantity); finished goods are booked when the order completes.
- **BOM versioning**: one active version per product; a BOM used by an order is frozen, so edit it via `new-version`.
- **Approval workflow** is linear: created → supervisor_reviewed → material_checked → production_started →
  quality_inspected → production_completed → manager_approved.
- **Errors** use `{"error": {"code", "message", "details"}}`, and the OpenAPI document describes that shape.
- **Shifts** use `SHIFT_UTC_OFFSET_MINUTES` to map shift times to UTC.
- **Password reset** tokens are returned in the API response outside production because no mail service is wired in.
- **Rate limiting** is in-memory (per process). Use Redis for multi-worker or multi-instance deployments.

## Known limits
Tests run on SQLite only. The Docker build and the PostgreSQL/MySQL paths have not been executed in this environment.
