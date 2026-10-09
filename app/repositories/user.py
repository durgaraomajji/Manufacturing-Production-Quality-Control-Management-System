from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import PasswordResetToken, RefreshToken, RevokedToken, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def get_by_email(self, db: Session, email: str) -> User | None:
        return db.scalars(
            select(User).where(User.email == email.lower(), User.is_deleted.is_(False))
        ).first()


user_repo = UserRepository(User, "User", search_fields=("email", "full_name"))
refresh_token_repo = BaseRepository(RefreshToken, "Refresh token")
revoked_token_repo = BaseRepository(RevokedToken, "Revoked token")
reset_token_repo = BaseRepository(PasswordResetToken, "Password reset token")
