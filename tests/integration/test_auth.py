from app.core.config import settings
from tests.helpers import Api

REG = {"email": "new.user@example.com", "full_name": "New User", "password": "Secret123"}


def test_register_login_and_me(client):
    r = client.post("/api/v1/auth/register", json=REG)
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "worker" and body["is_active"] is True and "hashed_password" not in body

    tokens = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    assert tokens["token_type"] == "bearer" and tokens["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == REG["email"]


def test_email_is_case_insensitive_and_unique(client):
    client.post("/api/v1/auth/register", json=REG)
    dup = client.post("/api/v1/auth/register", json={**REG, "email": REG["email"].upper()})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "conflict"
    ok = client.post("/api/v1/auth/login", json={"email": REG["email"].upper(), "password": REG["password"]})
    assert ok.status_code == 200


def test_self_registration_cannot_choose_a_role(client):
    r = client.post("/api/v1/auth/register", json={**REG, "role": "super_admin"})
    assert r.status_code == 201 and r.json()["role"] == "worker"


def test_weak_password_is_rejected(client):
    for bad in ("short1", "alllettersnodigits", "12345678"):
        r = client.post("/api/v1/auth/register", json={**REG, "password": bad})
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"


def test_wrong_password_and_unknown_user_look_identical(client):
    client.post("/api/v1/auth/register", json=REG)
    wrong = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": "Wrong1234"})
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "Wrong1234"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_protected_endpoint_requires_a_valid_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_token_rotation(client):
    client.post("/api/v1/auth/register", json=REG)
    tokens = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200 and first.json()["refresh_token"] != tokens["refresh_token"]
    # the old refresh token is single-use
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    # an access token is not accepted as a refresh token
    wrong_type = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert wrong_type.status_code == 401


def test_logout_revokes_access_and_refresh_tokens(client):
    client.post("/api/v1/auth/register", json=REG)
    tokens = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_deactivated_account_cannot_login_or_use_existing_token(client, admin, make_user):
    worker = make_user("worker")
    assert worker.get("/auth/me")["email"] == worker.email
    admin.post(f"/users/{worker.user['id']}/deactivate", expect=200)

    assert worker.raw("GET", "/auth/me").status_code == 403
    login = client.post("/api/v1/auth/login", json={"email": worker.email, "password": worker.password})
    assert login.status_code == 403

    admin.post(f"/users/{worker.user['id']}/activate", expect=200)
    assert client.post("/api/v1/auth/login", json={"email": worker.email, "password": worker.password}).status_code == 200


def test_admin_cannot_deactivate_self(admin):
    me = admin.get("/auth/me")
    admin.error("POST", f"/users/{me['id']}/deactivate", 422, "business_rule_violation")


def test_password_reset_flow(client):
    client.post("/api/v1/auth/register", json=REG)
    r = client.post("/api/v1/auth/password-reset/request", json={"email": REG["email"]})
    assert r.status_code == 200
    token = r.json()["reset_token"]
    assert token  # returned outside production because no mail service is configured

    bad = client.post("/api/v1/auth/password-reset/confirm", json={"token": "nope", "new_password": "Another123"})
    assert bad.status_code == 422
    ok = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Another123"})
    assert ok.status_code == 200

    assert client.post("/api/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": REG["email"], "password": "Another123"}).status_code == 200
    # the token cannot be reused
    again = client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Third12345"})
    assert again.status_code == 422


def test_password_reset_does_not_reveal_unknown_accounts(client):
    r = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert r.status_code == 200 and r.json()["reset_token"] is None


def test_password_reset_revokes_existing_sessions(client):
    client.post("/api/v1/auth/register", json=REG)
    tokens = client.post("/api/v1/auth/login", json={"email": REG["email"], "password": REG["password"]}).json()
    token = client.post("/api/v1/auth/password-reset/request", json={"email": REG["email"]}).json()["reset_token"]
    client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "Another123"})
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_swagger_oauth2_token_endpoint(client):
    client.post("/api/v1/auth/register", json=REG)
    r = client.post("/api/v1/auth/token", data={"username": REG["email"], "password": REG["password"]})
    assert r.status_code == 200 and r.json()["access_token"]


def test_login_is_audited(admin):
    logs = admin.get("/admin/audit-logs", action="user.login")
    assert logs["total"] >= 1 and logs["items"][0]["entity"] == "user"


def test_login_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "Wrong12345"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
