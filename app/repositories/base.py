"""Generic repository: data access only (queries, filters, search, sorting, pagination, soft delete).
Business rules live in app/services."""
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.utils.dt import utcnow
from app.utils.pagination import paginate

ModelT = TypeVar("ModelT")


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], label: str | None = None, search_fields: Sequence[str] = ()):
        self.model = model
        self.label = label or model.__name__
        self.search_fields = tuple(search_fields)
        self.soft_delete = hasattr(model, "is_deleted")

    # ---- reads
    def get(self, db: Session, obj_id: int, include_deleted: bool = False) -> ModelT | None:
        obj = db.get(self.model, obj_id)
        if obj is None or (self.soft_delete and obj.is_deleted and not include_deleted):
            return None
        return obj

    def get_or_404(self, db: Session, obj_id: int) -> ModelT:
        obj = self.get(db, obj_id)
        if obj is None:
            raise NotFoundError(self.label, obj_id)
        return obj

    def get_by(self, db: Session, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters)
        if self.soft_delete:
            stmt = stmt.where(self.model.is_deleted.is_(False))
        return db.scalars(stmt.limit(1)).first()

    def exists(self, db: Session, **filters: Any) -> bool:
        return self.get_by(db, **filters) is not None

    def list(
        self,
        db: Session,
        *,
        page: int = 1,
        size: int = 20,
        search: str | None = None,
        filters: dict[str, Any] | None = None,
        conditions: Sequence[ColumnElement] | None = None,
        sort_by: str | None = None,
        order: str = "desc",
    ) -> dict:
        stmt = select(self.model)
        if self.soft_delete:
            stmt = stmt.where(self.model.is_deleted.is_(False))
        for column, value in (filters or {}).items():
            if value is not None:
                stmt = stmt.where(getattr(self.model, column) == value)
        if conditions:
            stmt = stmt.where(*conditions)
        if search and self.search_fields:
            like = f"%{search.strip()}%"
            stmt = stmt.where(or_(*[getattr(self.model, f).ilike(like) for f in self.search_fields]))

        columns = self.model.__table__.columns
        sort_key = sort_by or "created_at" if "created_at" in columns else (sort_by or "id")
        if sort_key not in columns:
            raise BusinessRuleError(f"Invalid sort field '{sort_key}'. Allowed: {', '.join(sorted(columns.keys()))}")
        col = columns[sort_key]
        stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), self.model.id.desc() if order == "desc" else self.model.id.asc())
        return paginate(db, stmt, page, size)

    # ---- writes (flush only; the caller commits so a request is one transaction)
    def create(self, db: Session, data: dict[str, Any]) -> ModelT:
        obj = self.model(**data)
        db.add(obj)
        db.flush()
        return obj

    def update(self, db: Session, obj: ModelT, data: dict[str, Any]) -> ModelT:
        for key, value in data.items():
            setattr(obj, key, value)
        db.flush()
        return obj

    def soft_delete_obj(self, db: Session, obj: ModelT) -> None:
        if not self.soft_delete:
            raise BusinessRuleError(f"{self.label} does not support soft delete")
        obj.is_deleted = True
        obj.deleted_at = utcnow()
        db.flush()

    def hard_delete(self, db: Session, obj: ModelT) -> None:
        db.delete(obj)
        db.flush()
