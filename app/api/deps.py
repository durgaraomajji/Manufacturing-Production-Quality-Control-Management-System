"""Shared FastAPI dependencies: DB session, authentication, RBAC, list query params."""
from typing import Annotated, Literal

from fastapi import Depends, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import has_permission
from app.core.security import ACCESS, decode_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import user_repo
from app.services import auth_service
from app.utils.enums import Role

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/token", auto_error=False)

DB = Annotated[Session, Depends(get_db)]


def get_token_payload(db: DB, token: Annotated[str | None, Depends(oauth2_scheme)]) -> dict:
    if not token:
        raise AuthenticationError("Not authenticated")
    payload = decode_token(token, ACCESS)
    if auth_service.is_access_token_revoked(db, payload["jti"]):
        raise AuthenticationError("Token has been revoked")
    return payload


def get_current_user(db: DB, payload: Annotated[dict, Depends(get_token_payload)]) -> User:
    user = user_repo.get(db, int(payload["sub"]))
    if user is None:
        raise AuthenticationError("User no longer exists")
    if not user.is_active:
        raise PermissionDeniedError("Account is deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(*permissions: str):
    """Dependency factory: the current user must hold at least one of `permissions`."""
    def checker(user: CurrentUser) -> User:
        if not any(has_permission(user.role, p) for p in permissions):
            raise PermissionDeniedError(
                f"Role '{user.role.value}' is not allowed to perform this action (requires: {' or '.join(permissions)})")
        return user
    return checker


def require_roles(*roles: Role):
    def checker(user: CurrentUser) -> User:
        if user.role not in roles and user.role != Role.SUPER_ADMIN:
            raise PermissionDeniedError(f"Requires one of the roles: {', '.join(r.value for r in roles)}")
        return user
    return checker


def perm(*permissions: str):
    """Shorthand: `user: Annotated[User, perm(P.PLANT_WRITE)]`."""
    return Depends(require_permission(*permissions))


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


class ListQuery:
    """Standard list parameters: pagination, search and sorting."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=200),
        search: str | None = Query(None, description="Case-insensitive text search"),
        sort_by: str | None = Query(None, description="Column to sort by (default: created_at)"),
        order: Literal["asc", "desc"] = "desc",
    ):
        self.page, self.size, self.search, self.sort_by, self.order = page, size, search, sort_by, order

    def kwargs(self) -> dict:
        return {"page": self.page, "size": self.size, "search": self.search, "sort_by": self.sort_by, "order": self.order}


LQ = Annotated[ListQuery, Depends()]
