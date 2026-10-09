"""Authentication & account lifecycle (Level 1)."""
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BusinessRuleError, ConflictError, PermissionDeniedError
from app.models.user import PasswordResetToken, RefreshToken, RevokedToken, User
from app.repositories.user import user_repo
from app.services import audit_service
from app.utils.dt import utcnow
from app.utils.enums import AuditAction, Role


def create_user(db: Session, *, email: str, full_name: str, password: str, role: Role, phone: str | None = None,
                is_active: bool = True, actor_id: int | None = None) -> User:
    email = email.lower()
    if user_repo.get_by_email(db, email):
        raise ConflictError(f"A user with e-mail '{email}' already exists")
    user = user_repo.create(db, {
        "email": email, "full_name": full_name, "hashed_password": security.hash_password(password),
        "role": role, "phone": phone, "is_active": is_active,
    })
    audit_service.log(db, user_id=actor_id or user.id, action=AuditAction.USER_CREATE, entity="user", entity_id=user.id,
                      new=audit_service.snapshot(user))
    return user


def issue_tokens(db: Session, user: User) -> dict:
    access, _, _ = security.create_access_token(user.id, user.role.value)
    refresh, jti, exp = security.create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=exp))
    db.flush()
    return {
        "access_token": access, "refresh_token": refresh, "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


def login(db: Session, email: str, password: str, ip: str | None = None) -> dict:
    user = user_repo.get_by_email(db, email)
    # same error for unknown e-mail and wrong password (no user enumeration)
    if user is None or not security.verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect e-mail or password")
    if not user.is_active:
        raise PermissionDeniedError("Account is deactivated. Contact an administrator.")
    user.last_login_at = utcnow()
    tokens = issue_tokens(db, user)
    audit_service.log(db, user_id=user.id, action=AuditAction.USER_LOGIN, entity="user", entity_id=user.id, ip=ip)
    return tokens


def refresh(db: Session, refresh_token: str) -> dict:
    payload = security.decode_token(refresh_token, security.REFRESH)
    stored = db.scalars(select(RefreshToken).where(RefreshToken.jti == payload["jti"])).first()
    if stored is None or stored.revoked or stored.expires_at < utcnow():
        raise AuthenticationError("Refresh token is invalid or has been revoked")
    user = user_repo.get(db, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationError("User is inactive or no longer exists")
    stored.revoked = True  # rotation: every refresh token is single-use
    return issue_tokens(db, user)


def logout(db: Session, user: User, access_payload: dict, refresh_token: str | None) -> None:
    from datetime import datetime, timezone

    exp = datetime.fromtimestamp(access_payload["exp"], tz=timezone.utc).replace(tzinfo=None)
    if not db.scalars(select(RevokedToken.id).where(RevokedToken.jti == access_payload["jti"])).first():
        db.add(RevokedToken(jti=access_payload["jti"], expires_at=exp))
    if refresh_token:
        try:
            payload = security.decode_token(refresh_token, security.REFRESH)
        except AuthenticationError:
            return
        db.execute(update(RefreshToken).where(RefreshToken.jti == payload["jti"], RefreshToken.user_id == user.id).values(revoked=True))
    db.flush()


def is_access_token_revoked(db: Session, jti: str) -> bool:
    return db.scalars(select(RevokedToken.id).where(RevokedToken.jti == jti)).first() is not None


def revoke_all_refresh_tokens(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)).values(revoked=True))


# ---------------------------------------------------------------- password reset
def request_password_reset(db: Session, email: str) -> str | None:
    """Returns the raw token (to be e-mailed) or None when the account does not exist.
    The API answers identically in both cases so accounts cannot be enumerated."""
    user = user_repo.get_by_email(db, email)
    if user is None or not user.is_active:
        return None
    raw, hashed = security.generate_reset_token()
    db.add(PasswordResetToken(
        user_id=user.id, token_hash=hashed, expires_at=utcnow() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    ))
    db.flush()
    return raw


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> User:
    record = db.scalars(select(PasswordResetToken).where(PasswordResetToken.token_hash == security.hash_token(raw_token))).first()
    if record is None or record.used or record.expires_at < utcnow():
        raise BusinessRuleError("Password reset token is invalid or has expired")
    user = user_repo.get(db, record.user_id)
    if user is None:
        raise BusinessRuleError("Password reset token is invalid or has expired")
    user.hashed_password = security.hash_password(new_password)
    record.used = True
    revoke_all_refresh_tokens(db, user.id)  # force re-login everywhere
    db.flush()
    return user


# ---------------------------------------------------------------- account management
def set_active(db: Session, user: User, active: bool, actor: User) -> User:
    if user.id == actor.id and not active:
        raise BusinessRuleError("You cannot deactivate your own account")
    previous = {"is_active": user.is_active}
    user.is_active = active
    if not active:
        revoke_all_refresh_tokens(db, user.id)
    audit_service.log(db, user_id=actor.id, action=AuditAction.USER_UPDATE, entity="user", entity_id=user.id,
                      previous=previous, new={"is_active": active})
    db.flush()
    return user
