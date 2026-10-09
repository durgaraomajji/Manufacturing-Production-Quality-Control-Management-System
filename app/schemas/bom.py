from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class BOMItemIn(BaseModel):
    material_id: int
    quantity_per_unit: float = Field(gt=0)


class BOMItemUpdate(BaseModel):
    quantity_per_unit: float = Field(gt=0)


class BOMCreate(BaseModel):
    product_id: int
    name: str | None = Field(default=None, max_length=150)
    notes: str | None = None
    items: list[BOMItemIn] = Field(min_length=1)
    activate: bool = False

    @model_validator(mode="after")
    def _no_duplicate_materials(self):
        ids = [i.material_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("A material may appear only once per BOM")
        return self


class BOMUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    notes: str | None = None
    items: list[BOMItemIn] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _no_duplicate_materials(self):
        if self.items:
            ids = [i.material_id for i in self.items]
            if len(ids) != len(set(ids)):
                raise ValueError("A material may appear only once per BOM")
        return self


class BOMItemRead(ORMModel):
    id: int
    material_id: int
    quantity_per_unit: float


class BOMRead(ORMModel):
    id: int
    product_id: int
    version: int
    name: str | None
    notes: str | None
    is_active: bool
    items: list[BOMItemRead]
    created_at: datetime
    updated_at: datetime
