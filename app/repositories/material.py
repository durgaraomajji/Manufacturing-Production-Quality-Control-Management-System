from app.models.inventory import InventoryTransaction
from app.models.material import Material, MaterialCategory
from app.repositories.base import BaseRepository

material_repo = BaseRepository(Material, "Material", search_fields=("code", "name", "supplier_reference"))
material_category_repo = BaseRepository(MaterialCategory, "Material category", search_fields=("name",))
transaction_repo = BaseRepository(InventoryTransaction, "Inventory transaction", search_fields=("remarks",))
