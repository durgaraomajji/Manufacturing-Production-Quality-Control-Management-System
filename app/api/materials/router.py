from typing import Annotated

from fastapi import APIRouter, Response

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.user import User
from app.repositories.material import material_category_repo, material_repo
from app.schemas.common import Page
from app.schemas.material import (
    MaterialCategoryCreate, MaterialCategoryRead, MaterialCreate, MaterialRead, MaterialUpdate, StockAdjust, StockIn,
    StockOut, TransactionRead,
)
from app.services import audit_service, material_service
from app.utils.pagination import paginate
from app.core.exceptions import ConflictError
from app.utils.enums import MaterialStatus

router = APIRouter(prefix="/materials", tags=["Raw Materials"])
category_router = APIRouter(prefix="/material-categories", tags=["Raw Materials"])


@category_router.post("", response_model=MaterialCategoryRead, status_code=201)
def create_category(body: MaterialCategoryCreate, db: DB, user: Annotated[User, perm(P.MATERIAL_WRITE)]):
    if material_category_repo.exists(db, name=body.name):
        raise ConflictError(f"Category '{body.name}' already exists")
    category = material_category_repo.create(db, body.model_dump())
    audit_service.log(db, user_id=user.id, action="material_category.create", entity="material_category", entity_id=category.id,
                      new=audit_service.snapshot(category))
    db.commit()
    return category


@category_router.get("", response_model=Page[MaterialCategoryRead])
def list_categories(q: LQ, db: DB, _: Annotated[User, perm(P.MATERIAL_READ)]):
    return material_category_repo.list(db, **q.kwargs())


@router.post("", response_model=MaterialRead, status_code=201)
def create_material(body: MaterialCreate, db: DB, user: Annotated[User, perm(P.MATERIAL_WRITE)]):
    material = material_service.create_material(db, body.model_dump(), user)
    db.commit()
    return material


@router.get("", response_model=Page[MaterialRead])
def list_materials(q: LQ, db: DB, _: Annotated[User, perm(P.MATERIAL_READ)], category_id: int | None = None,
                   status: MaterialStatus | None = None, supplier_reference: str | None = None):
    return material_repo.list(db, **q.kwargs(),
                              filters={"category_id": category_id, "status": status, "supplier_reference": supplier_reference})


@router.get("/low-stock", response_model=list[MaterialRead], summary="Materials at or below their minimum / reorder level")
def low_stock(db: DB, _: Annotated[User, perm(P.MATERIAL_READ)]):
    return material_service.low_stock(db)


@router.get("/{material_id}", response_model=MaterialRead)
def get_material(material_id: int, db: DB, _: Annotated[User, perm(P.MATERIAL_READ)]):
    return material_repo.get_or_404(db, material_id)


@router.patch("/{material_id}", response_model=MaterialRead)
def update_material(material_id: int, body: MaterialUpdate, db: DB, user: Annotated[User, perm(P.MATERIAL_WRITE)]):
    material = material_repo.get_or_404(db, material_id)
    previous = audit_service.snapshot(material)
    material_repo.update(db, material, body.model_dump(exclude_unset=True))
    audit_service.log(db, user_id=user.id, action="material.update", entity="material", entity_id=material.id,
                      previous=previous, new=audit_service.snapshot(material))
    db.commit()
    return material


@router.delete("/{material_id}", status_code=204)
def delete_material(material_id: int, db: DB, user: Annotated[User, perm(P.MATERIAL_WRITE)]):
    material_service.delete_material(db, material_repo.get_or_404(db, material_id), user)
    db.commit()
    return Response(status_code=204)


@router.post("/{material_id}/stock-in", response_model=TransactionRead, status_code=201)
def stock_in(material_id: int, body: StockIn, db: DB, user: Annotated[User, perm(P.STOCK_MOVE)]):
    txn = material_service.stock_in(db, material_repo.get_or_404(db, material_id), body.quantity, user, body.reference, body.remarks)
    db.commit()
    return txn


@router.post("/{material_id}/stock-out", response_model=TransactionRead, status_code=201)
def stock_out(material_id: int, body: StockOut, db: DB, user: Annotated[User, perm(P.STOCK_MOVE)]):
    txn = material_service.stock_out(db, material_repo.get_or_404(db, material_id), body.quantity, user, body.remarks)
    db.commit()
    return txn


@router.post("/{material_id}/adjust", response_model=TransactionRead, status_code=201,
             summary="Correct stock to a counted quantity (records an adjustment transaction)")
def adjust_stock(material_id: int, body: StockAdjust, db: DB, user: Annotated[User, perm(P.INVENTORY_ADJUST)]):
    txn = material_service.adjust(db, material_repo.get_or_404(db, material_id), body.new_quantity, user, body.reason)
    db.commit()
    return txn


@router.get("/{material_id}/usage-history", response_model=Page[TransactionRead],
            summary="Material usage history (production consumption and manual stock-outs)")
def usage_history(material_id: int, q: LQ, db: DB, _: Annotated[User, perm(P.MATERIAL_READ)]):
    material_repo.get_or_404(db, material_id)
    return paginate(db, material_service.usage_history_stmt(material_id), q.page, q.size)
