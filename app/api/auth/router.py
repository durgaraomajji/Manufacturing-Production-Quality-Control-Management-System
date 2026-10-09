from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DB, LQ, CurrentUser, client_ip, get_token_payload, perm
from app.core.config import settings
from app.core.permissions import P
from app.core.rate_limit import login_rate_limit
from app.models.user import User
from app.repositories.user import user_repo
from app.schemas.auth import (
    LoginRequest, LogoutRequest, PasswordResetConfirm, PasswordResetRequest, PasswordResetResponse, RefreshRequest,
    RegisterRequest, TokenResponse, UserCreate, UserRead, UserUpdate,
)
from app.schemas.common import Message, Page
from app.services import audit_service, auth_service
from app.utils.enums import Role

router = APIRouter(prefix="/auth", tags=["Authentication"])
users_router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/register", response_model=UserRead, status_code=201, dependencies=[Depends(login_rate_limit)],
             summary="Self-register (always creates a 'worker' account)")
def register(body: RegisterRequest, db: DB):
    user = auth_service.create_user(db, email=body.email, full_name=body.full_name, password=body.password,
                                    role=Role.WORKER, phone=body.phone)
    db.commit()
    return user


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
def login(body: LoginRequest, request: Request, db: DB):
    tokens = auth_service.login(db, body.email, body.password, client_ip(request))
    db.commit()
    return tokens


@router.post("/token", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)],
             summary="OAuth2 password flow (used by the Swagger 'Authorize' button; username = e-mail)")
def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], request: Request, db: DB):
    tokens = auth_service.login(db, form.username, form.password, client_ip(request))
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(login_rate_limit)])
def refresh(body: RefreshRequest, db: DB):
    tokens = auth_service.refresh(db, body.refresh_token)
    db.commit()
    return tokens


@router.post("/logout", response_model=Message)
def logout(body: LogoutRequest, db: DB, user: CurrentUser, payload: Annotated[dict, Depends(get_token_payload)]):
    auth_service.logout(db, user, payload, body.refresh_token)
    db.commit()
    return Message(message="Logged out")


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user


@router.post("/password-reset/request", response_model=PasswordResetResponse, dependencies=[Depends(login_rate_limit)])
def password_reset_request(body: PasswordResetRequest, db: DB):
    raw = auth_service.request_password_reset(db, body.email)
    db.commit()
    return PasswordResetResponse(
        message="If the account exists, a password reset link has been sent",
        # No mail service is wired in: outside production the token is returned so the flow can be exercised.
        reset_token=raw if (raw and not settings.is_production) else None,
    )


@router.post("/password-reset/confirm", response_model=Message, dependencies=[Depends(login_rate_limit)])
def password_reset_confirm(body: PasswordResetConfirm, db: DB):
    auth_service.confirm_password_reset(db, body.token, body.new_password)
    db.commit()
    return Message(message="Password has been reset")


# ------------------------------------------------------------------ user administration
@users_router.post("", response_model=UserRead, status_code=201)
def create_user(body: UserCreate, db: DB, actor: Annotated[User, perm(P.USER_MANAGE)]):
    user = auth_service.create_user(db, email=body.email, full_name=body.full_name, password=body.password, role=body.role,
                                    phone=body.phone, is_active=body.is_active, actor_id=actor.id)
    db.commit()
    return user


@users_router.get("", response_model=Page[UserRead])
def list_users(q: LQ, db: DB, _: Annotated[User, perm(P.USER_READ)], role: Role | None = None, is_active: bool | None = None):
    return user_repo.list(db, **q.kwargs(), filters={"role": role, "is_active": is_active})


@users_router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: DB, _: Annotated[User, perm(P.USER_READ)]):
    return user_repo.get_or_404(db, user_id)


@users_router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, body: UserUpdate, db: DB, actor: Annotated[User, perm(P.USER_MANAGE)]):
    user = user_repo.get_or_404(db, user_id)
    previous = audit_service.snapshot(user)
    user_repo.update(db, user, body.model_dump(exclude_unset=True))
    audit_service.log(db, user_id=actor.id, action="user.update", entity="user", entity_id=user.id, previous=previous,
                      new=audit_service.snapshot(user))
    db.commit()
    return user


@users_router.post("/{user_id}/activate", response_model=UserRead)
def activate_user(user_id: int, db: DB, actor: Annotated[User, perm(P.USER_MANAGE)]):
    user = auth_service.set_active(db, user_repo.get_or_404(db, user_id), True, actor)
    db.commit()
    return user


@users_router.post("/{user_id}/deactivate", response_model=UserRead)
def deactivate_user(user_id: int, db: DB, actor: Annotated[User, perm(P.USER_MANAGE)]):
    user = auth_service.set_active(db, user_repo.get_or_404(db, user_id), False, actor)
    db.commit()
    return user
