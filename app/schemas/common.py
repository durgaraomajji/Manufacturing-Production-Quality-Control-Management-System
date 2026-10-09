from datetime import datetime
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.utils.dt import to_naive_utc

T = TypeVar("T")

# Any incoming datetime is normalised to naive UTC (what the database stores)
UTCDateTime = Annotated[datetime, AfterValidator(to_naive_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


class Message(BaseModel):
    message: str


class Reason(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
