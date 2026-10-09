from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, enum_col
from app.utils.enums import ApprovalStage


class ApprovalLog(Entity):
    """History of every approval-workflow step taken on a production order."""
    __tablename__ = "approval_logs"

    order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), index=True)
    from_stage: Mapped[ApprovalStage | None] = enum_col(ApprovalStage, nullable=True)
    to_stage: Mapped[ApprovalStage] = enum_col(ApprovalStage)
    action: Mapped[str] = mapped_column(String(60))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
