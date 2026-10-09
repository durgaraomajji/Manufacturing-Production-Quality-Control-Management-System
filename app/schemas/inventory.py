from pydantic import BaseModel

from app.schemas.material import MaterialRead  # noqa: F401  (re-export for convenience)
from app.schemas.material import ProductStockAdjust, TransactionRead  # noqa: F401


class InventorySummary(BaseModel):
    total_materials: int
    low_stock_materials: int
    out_of_stock_materials: int
    total_finished_goods_units: float
    transactions_today: int
