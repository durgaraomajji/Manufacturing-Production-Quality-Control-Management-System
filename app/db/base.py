"""Declarative base, reusable mixins and the enum column helper."""
from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.dt import utcnow


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Entity(Base, TimestampMixin):
    """Abstract base: integer PK + created/updated timestamps."""
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True)


class SoftDeleteEntity(Entity, SoftDeleteMixin):
    """Abstract base for records that are never physically deleted."""
    __abstract__ = True


def enum_col(enum_cls: type[Enum], **kwargs):
    """Store an Enum as a plain VARCHAR holding the enum *value* (portable across MySQL/PostgreSQL/SQLite)."""
    return mapped_column(
        SAEnum(enum_cls, native_enum=False, length=40, values_callable=lambda e: [m.value for m in e], validate_strings=True),
        **kwargs,
    )
