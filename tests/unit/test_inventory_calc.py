"""Inventory calculations exercised directly against the service layer."""
import pytest
from sqlalchemy import select

from app.core.exceptions import BusinessRuleError, InsufficientStockError
from app.models.inventory import InventoryTransaction
from app.models.material import Material
from app.models.notification import Notification
from app.models.product import Product
from app.models.user import User
from app.services import inventory_service
from app.utils.enums import MovementType, NotificationType


@pytest.fixture
def user(db):
    return db.scalars(select(User)).first()


@pytest.fixture
def material(db):
    m = Material(code="M-1", name="Steel", unit="kg", minimum_stock_level=20, reorder_level=40)
    db.add(m)
    db.commit()
    return m


def test_receipts_and_consumption_update_the_balance(db, user, material):
    inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 100, user_id=user.id)
    inventory_service.apply_material_movement(db, material, MovementType.CONSUMPTION, -35.5, user_id=user.id)
    db.commit()
    assert db.get(Material, material.id).available_quantity == 64.5


def test_ledger_keeps_a_consistent_balance_chain(db, user, material):
    for movement, delta in [(MovementType.RECEIPT, 100), (MovementType.STOCK_OUT, -30), (MovementType.RECEIPT, 5), (MovementType.CONSUMPTION, -10)]:
        inventory_service.apply_material_movement(db, material, movement, delta, user_id=user.id)
    db.commit()
    rows = db.scalars(select(InventoryTransaction).order_by(InventoryTransaction.id)).all()
    assert [r.balance_after for r in rows] == [100, 70, 75, 65]
    for r in rows:
        assert r.balance_before + r.delta == r.balance_after
        assert r.quantity == abs(r.delta) and r.performed_by_id == user.id
    assert rows[0].balance_before == 0


def test_negative_inventory_is_prevented_and_nothing_is_written(db, user, material):
    inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 10, user_id=user.id)
    db.commit()
    with pytest.raises(InsufficientStockError) as exc:
        inventory_service.apply_material_movement(db, material, MovementType.STOCK_OUT, -10.001, user_id=user.id)
    assert exc.value.details["available"] == 10
    db.rollback()
    assert db.get(Material, material.id).available_quantity == 10
    assert db.scalars(select(InventoryTransaction)).all().__len__() == 1


def test_can_consume_exactly_everything(db, user, material):
    inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 12.5, user_id=user.id)
    inventory_service.apply_material_movement(db, material, MovementType.CONSUMPTION, -12.5, user_id=user.id)
    assert material.available_quantity == 0


def test_float_noise_does_not_leak_into_balances(db, user, material):
    for _ in range(10):
        inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 0.1, user_id=user.id)
    assert material.available_quantity == 1.0


def test_adjustment_to_counted_quantity(db, user, material):
    inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 50, user_id=user.id)
    up = inventory_service.adjust_to(db, material, 60, user_id=user.id, reason="found stock")
    down = inventory_service.adjust_to(db, material, 45, user_id=user.id, reason="damaged")
    assert (up.delta, up.movement_type) == (10, MovementType.ADJUSTMENT) and down.delta == -15
    assert material.available_quantity == 45
    with pytest.raises(BusinessRuleError):
        inventory_service.adjust_to(db, material, 45, user_id=user.id, reason="no change")


def test_finished_goods_movements(db, user):
    p = Product(sku="P-1", name="Widget")
    db.add(p)
    db.commit()
    inventory_service.apply_product_movement(db, p, MovementType.FINISHED_GOODS, 48, user_id=user.id)
    # rejected goods are logged but never enter stock
    rej = inventory_service.apply_product_movement(db, p, MovementType.REJECTED_GOODS, 0, quantity=2, user_id=user.id)
    assert p.stock_quantity == 48 and rej.quantity == 2 and rej.delta == 0
    with pytest.raises(InsufficientStockError):
        inventory_service.apply_product_movement(db, p, MovementType.STOCK_OUT, -49, user_id=user.id)


def test_low_stock_notification_when_threshold_is_crossed(db, user, material):
    inventory_service.apply_material_movement(db, material, MovementType.RECEIPT, 100, user_id=user.id)
    inventory_service.apply_material_movement(db, material, MovementType.CONSUMPTION, -50, user_id=user.id)  # 50 > reorder 40
    assert db.scalars(select(Notification).where(Notification.type == NotificationType.LOW_STOCK)).all() == []
    inventory_service.apply_material_movement(db, material, MovementType.CONSUMPTION, -15, user_id=user.id)  # 35 <= reorder 40
    notes = db.scalars(select(Notification).where(Notification.type == NotificationType.LOW_STOCK)).all()
    assert len(notes) >= 1 and "M-1" in notes[0].title
    # de-duplicated while unread
    inventory_service.apply_material_movement(db, material, MovementType.CONSUMPTION, -5, user_id=user.id)
    assert len(db.scalars(select(Notification).where(Notification.type == NotificationType.LOW_STOCK)).all()) == len(notes)


def test_is_low_stock_property():
    assert Material(code="a", name="a", available_quantity=5, minimum_stock_level=10, reorder_level=0).is_low_stock
    assert not Material(code="a", name="a", available_quantity=50, minimum_stock_level=10, reorder_level=20).is_low_stock
    assert not Material(code="a", name="a", available_quantity=0, minimum_stock_level=0, reorder_level=0).is_low_stock
