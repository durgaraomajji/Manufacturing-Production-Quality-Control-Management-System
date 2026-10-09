import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel
from app.utils.enums import Role


def validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(max_length=128)
    phone: str | None = Field(default=None, max_length=30)

    _check_password = field_validator("password")(validate_password_strength)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(max_length=128)

    _check_password = field_validator("new_password")(validate_password_strength)


class PasswordResetResponse(BaseModel):
    message: str
    reset_token: str | None = None  # only returned outside production (no e-mail service wired in)


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(max_length=128)
    role: Role = Role.WORKER
    phone: str | None = Field(default=None, max_length=30)
    is_active: bool = True

    _check_password = field_validator("password")(validate_password_strength)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    role: Role | None = None


class UserRead(ORMModel):
    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    phone: str | None
    last_login_at: datetime | None
    created_at: datetime
