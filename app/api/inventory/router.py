from datetime import date
from typing import Annotated

from fastapi import APIRouter

from app.api.deps import DB, LQ, perm
from app.core.permissions import P
from app.models.inventory import InventoryTransaction
from app.models.user import User
from app.repositories.material import transaction_repo
from app.repositories.product import product_repo
from app.schemas.common import Page
from app.schemas.inventory import InventorySummary, ProductStockAdjust, TransactionRead
from app.schemas.product import ProductRead
from app.services import inventory_service
from app.utils.dt import day_end_exclusive, day_start
from app.utils.enums import MovementType

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/transactions", response_model=Page[TransactionRead], summary="Inventory movement history (immutable ledger)")
def list_transactions(q: LQ, db: DB, _: Annotated[User, perm(P.INVENTORY_READ)], material_id: int | None = None,
                      product_id: int | None = None, movement_type: MovementType | None = None,
                      batch_id: int | None = None, date_from: date | None = None, date_to: date | None = None):
    conditions = []
    if date_from:
        conditions.append(InventoryTransaction.created_at >= day_start(date_from))
    if date_to:
        conditions.append(InventoryTransaction.created_at < day_end_exclusive(date_to))
    return transaction_repo.list(db, **q.kwargs(), conditions=conditions, filters={
        "material_id": material_id, "product_id": product_id, "movement_type": movement_type, "batch_id": batch_id})


@router.get("/summary", response_model=InventorySummary)
def summary(db: DB, _: Annotated[User, perm(P.INVENTORY_READ)]):
    return inventory_service.summary(db)


@router.get("/finished-goods", response_model=Page[ProductRead], summary="Finished-goods stock per product")
def finished_goods(q: LQ, db: DB, _: Annotated[User, perm(P.INVENTORY_READ)]):
    return product_repo.list(db, **q.kwargs())


@router.post("/finished-goods/{product_id}/adjust", response_model=TransactionRead, status_code=201,
             summary="Correct finished-goods stock to a counted quantity")
def adjust_finished_goods(product_id: int, body: ProductStockAdjust, db: DB, user: Annotated[User, perm(P.INVENTORY_ADJUST)]):
    product = product_repo.get_or_404(db, product_id)
    txn = inventory_service.adjust_to(db, product, body.new_quantity, user_id=user.id, reason=body.reason)
    db.commit()
    return txn
