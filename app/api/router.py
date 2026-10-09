"""Aggregates every router under the versioned API prefix."""
from fastapi import APIRouter

from app.api.admin.router import router as admin_router
from app.api.auth.router import router as auth_router
from app.api.auth.router import users_router
from app.api.inventory.router import router as inventory_router
from app.api.machines.router import router as machines_router
from app.api.maintenance.router import downtime_router
from app.api.maintenance.router import router as maintenance_router
from app.api.materials.router import category_router as material_category_router
from app.api.materials.router import router as materials_router
from app.api.plants.router import router as plants_router
from app.api.production.router import router as production_router
from app.api.products.router import router as products_router
from app.api.quality.router import router as quality_router
from app.api.reports.router import router as reports_router

api_router = APIRouter()
for r in (auth_router, users_router, plants_router, products_router, material_category_router, materials_router,
          machines_router, production_router, quality_router, maintenance_router, downtime_router, inventory_router,
          reports_router, admin_router):
    api_router.include_router(r)
