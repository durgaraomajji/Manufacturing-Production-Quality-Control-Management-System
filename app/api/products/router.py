from typing import Annotated

from fastapi import APIRouter, Response

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.user import User
from app.repositories.product import bom_repo, product_category_repo, product_repo
from app.schemas.bom import BOMCreate, BOMItemIn, BOMItemUpdate, BOMRead, BOMUpdate
from app.schemas.common import Page
from app.schemas.product import (
    CategoryCreate, CategoryRead, CategoryUpdate, ProductCreate, ProductRead, ProductUpdate,
)
from app.services import bom_service, product_service
from app.utils.enums import ProductStatus

router = APIRouter(tags=["Products & BOM"])


# ------------------------------------------------------------------ categories
@router.post("/product-categories", response_model=CategoryRead, status_code=201)
def create_category(body: CategoryCreate, db: DB, user: Annotated[User, perm(P.PRODUCT_WRITE)]):
    category = product_service.create_category(db, body.model_dump(), user)
    db.commit()
    return category


@router.get("/product-categories", response_model=Page[CategoryRead])
def list_categories(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return product_category_repo.list(db, **q.kwargs())


@router.patch("/product-categories/{category_id}", response_model=CategoryRead)
def update_category(category_id: int, body: CategoryUpdate, db: DB, user: Annotated[User, perm(P.PRODUCT_WRITE)]):
    category = product_service.update_category(db, product_category_repo.get_or_404(db, category_id),
                                               body.model_dump(exclude_unset=True), user)
    db.commit()
    return category


# ------------------------------------------------------------------ products
@router.post("/products", response_model=ProductRead, status_code=201)
def create_product(body: ProductCreate, db: DB, user: Annotated[User, perm(P.PRODUCT_WRITE)]):
    product = product_service.create_product(db, body.model_dump(), user)
    db.commit()
    return product


@router.get("/products", response_model=Page[ProductRead])
def list_products(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)], category_id: int | None = None,
                  status: ProductStatus | None = None, unit_of_measure: str | None = None):
    return product_repo.list(db, **q.kwargs(),
                             filters={"category_id": category_id, "status": status, "unit_of_measure": unit_of_measure})


@router.get("/products/{product_id}", response_model=ProductRead)
def get_product(product_id: int, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return product_repo.get_or_404(db, product_id)


@router.patch("/products/{product_id}", response_model=ProductRead)
def update_product(product_id: int, body: ProductUpdate, db: DB, user: Annotated[User, perm(P.PRODUCT_WRITE)]):
    product = product_service.update_product(db, product_repo.get_or_404(db, product_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return product


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: DB, user: Annotated[User, perm(P.PRODUCT_WRITE)]):
    product_service.delete_product(db, product_repo.get_or_404(db, product_id), user)
    db.commit()
    return Response(status_code=204)


@router.get("/products/{product_id}/boms", response_model=Page[BOMRead], summary="All BOM versions of a product")
def product_boms(product_id: int, q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    product_repo.get_or_404(db, product_id)
    return bom_repo.list(db, **{**q.kwargs(), "sort_by": q.sort_by or "version"}, filters={"product_id": product_id})


# ------------------------------------------------------------------ BOM
@router.post("/boms", response_model=BOMRead, status_code=201)
def create_bom(body: BOMCreate, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.create_bom(db, body.model_dump(), user)
    db.commit()
    return bom


@router.get("/boms", response_model=Page[BOMRead])
def list_boms(q: LQ, db: DB, _: Annotated[User, perm(P.MASTER_READ)], product_id: int | None = None,
              is_active: bool | None = None):
    return bom_repo.list(db, **q.kwargs(), filters={"product_id": product_id, "is_active": is_active})


@router.get("/boms/{bom_id}", response_model=BOMRead)
def get_bom(bom_id: int, db: DB, _: Annotated[User, perm(P.MASTER_READ)]):
    return bom_repo.get_or_404(db, bom_id)


@router.patch("/boms/{bom_id}", response_model=BOMRead)
def update_bom(bom_id: int, body: BOMUpdate, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.update_bom(db, bom_repo.get_or_404(db, bom_id), body.model_dump(exclude_unset=True), user)
    db.commit()
    return bom


@router.post("/boms/{bom_id}/items", response_model=BOMRead, status_code=201)
def add_bom_item(bom_id: int, body: BOMItemIn, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.add_item(db, bom_repo.get_or_404(db, bom_id), body.material_id, body.quantity_per_unit, user)
    db.commit()
    return bom


@router.patch("/boms/{bom_id}/items/{material_id}", response_model=BOMRead)
def update_bom_item(bom_id: int, material_id: int, body: BOMItemUpdate, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.update_item(db, bom_repo.get_or_404(db, bom_id), material_id, body.quantity_per_unit, user)
    db.commit()
    return bom


@router.delete("/boms/{bom_id}/items/{material_id}", response_model=BOMRead)
def remove_bom_item(bom_id: int, material_id: int, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.remove_item(db, bom_repo.get_or_404(db, bom_id), material_id, user)
    db.commit()
    return bom


@router.post("/boms/{bom_id}/activate", response_model=BOMRead, summary="Activate (deactivates the product's other BOM versions)")
def activate_bom(bom_id: int, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.activate(db, bom_repo.get_or_404(db, bom_id), user)
    db.commit()
    return bom


@router.post("/boms/{bom_id}/deactivate", response_model=BOMRead)
def deactivate_bom(bom_id: int, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.deactivate(db, bom_repo.get_or_404(db, bom_id), user)
    db.commit()
    return bom


@router.post("/boms/{bom_id}/new-version", response_model=BOMRead, status_code=201,
             summary="Copy a BOM into the next (inactive) version so it can be edited")
def new_bom_version(bom_id: int, db: DB, user: Annotated[User, perm(P.BOM_WRITE)]):
    bom = bom_service.new_version(db, bom_repo.get_or_404(db, bom_id), user)
    db.commit()
    return bom
