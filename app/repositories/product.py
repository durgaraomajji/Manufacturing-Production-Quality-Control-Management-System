from app.models.bom import BOM
from app.models.product import Product, ProductCategory
from app.repositories.base import BaseRepository

product_repo = BaseRepository(Product, "Product", search_fields=("sku", "name", "description"))
product_category_repo = BaseRepository(ProductCategory, "Product category", search_fields=("name",))
bom_repo = BaseRepository(BOM, "BOM", search_fields=("name",))
