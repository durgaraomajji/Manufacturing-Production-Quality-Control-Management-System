"""Unit tests for security helpers, rate limiter, datetime helpers, quality evaluation and shifts."""
from datetime import datetime, time, timedelta, timezone

import jwt
import pytest

from app.core import security
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import RateLimiter
from app.models.worker import Shift
from app.schemas.auth import validate_password_strength
from app.services.quality_service import evaluate_parameter
from app.utils.dt import overlap_minutes, to_naive_utc


def test_password_hashing_is_salted_and_verifiable():
    h1, h2 = security.hash_password("Secret123"), security.hash_password("Secret123")
    assert h1 != h2 and h1 != "Secret123"
    assert security.verify_password("Secret123", h1) and not security.verify_password("secret123", h1)
    assert not security.verify_password("x", "not-a-bcrypt-hash")


def test_jwt_access_and_refresh_tokens_are_not_interchangeable():
    access, jti, exp = security.create_access_token(7, "worker")
    payload = security.decode_token(access, security.ACCESS)
    assert payload["sub"] == "7" and payload["role"] == "worker" and payload["jti"] == jti
    with pytest.raises(AuthenticationError):
        security.decode_token(access, security.REFRESH)
    refresh, _, _ = security.create_refresh_token(7)
    with pytest.raises(AuthenticationError):
        security.decode_token(refresh, security.ACCESS)


def test_expired_and_tampered_tokens_are_rejected():
    expired = jwt.encode({"sub": "1", "type": "access", "jti": "x", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
                         settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(AuthenticationError, match="expired"):
        security.decode_token(expired, security.ACCESS)
    forged = jwt.encode({"sub": "1", "type": "access", "jti": "x", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                        "another-secret-another-secret-another-secret", algorithm=settings.ALGORITHM)
    with pytest.raises(AuthenticationError):
        security.decode_token(forged, security.ACCESS)


def test_reset_tokens_are_stored_hashed():
    raw, hashed = security.generate_reset_token()
    assert raw != hashed and security.hash_token(raw) == hashed and len(hashed) == 64


def test_password_strength_rules():
    assert validate_password_strength("Abcdef12") == "Abcdef12"
    for bad in ("short1A", "nodigitsHere", "12345678"):
        with pytest.raises(ValueError):
            validate_password_strength(bad)


def test_rate_limiter_sliding_window():
    rl = RateLimiter()
    assert [rl.hit("a", 3)[0] for _ in range(4)] == [True, True, True, False]
    allowed, retry = rl.hit("a", 3)
    assert not allowed and 1 <= retry <= 61
    assert rl.hit("b", 3)[0] is True  # separate key
    assert rl.hit("a", 3, window_seconds=0)[0] is True  # window elapsed


def test_datetime_helpers():
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert to_naive_utc(aware) == datetime(2026, 1, 1, 6, 30)
    a, b = datetime(2026, 1, 1, 10), datetime(2026, 1, 1, 12)
    assert overlap_minutes(a, b, datetime(2026, 1, 1, 11), datetime(2026, 1, 1, 13)) == 60
    assert overlap_minutes(a, b, datetime(2026, 1, 2), datetime(2026, 1, 3)) == 0
    assert overlap_minutes(a, b, datetime(2026, 1, 1, 0), datetime(2026, 1, 2)) == 120


@pytest.mark.parametrize("expected,actual,tol,explicit,result", [
    ("10", "10", None, None, True), ("10", "10.4", 0.5, None, True), ("10", "10.6", 0.5, None, False),
    ("10", "9.5", 0.5, None, True), ("10", "10.1", None, None, False), ("Red", "red", None, None, True),
    ("Red", "Blue", None, None, False), ("10", "99", None, True, True), ("10", "10", None, False, False),
])
def test_inspection_parameter_verdict(expected, actual, tol, explicit, result):
    assert evaluate_parameter(expected, actual, tol, explicit) is result


def test_shift_contains_handles_midnight_crossing():
    morning = Shift(start_time=time(6), end_time=time(14))
    night = Shift(start_time=time(22), end_time=time(6))
    assert morning.contains(time(6)) and morning.contains(time(13, 59)) and not morning.contains(time(14))
    assert night.contains(time(23)) and night.contains(time(2)) and night.contains(time(22)) and not night.contains(time(6))
    assert not night.contains(time(12))
