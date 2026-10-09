import os

# Settings are read at import time, so configure the environment first.
os.environ.update({
    "DATABASE_URL": "sqlite://",          # in-memory SQLite shared through a StaticPool
    "ENVIRONMENT": "testing",
    "BCRYPT_ROUNDS": "4",
    "RATE_LIMIT_ENABLED": "false",
    "AUTO_CREATE_TABLES": "true",
    "ENABLE_BACKGROUND_CHECKS": "false",
    "SECRET_KEY": "test-secret-key-test-secret-key-1234567890",
    "FIRST_SUPERUSER_EMAIL": "admin@example.com",
    "FIRST_SUPERUSER_PASSWORD": "Admin@12345",
})

import logging  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.rate_limit import limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.init_db import seed_defaults  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from tests.helpers import Api  # noqa: E402

logging.getLogger("app.request").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


@pytest.fixture(autouse=True)
def _fresh_database():
    """Every test starts from an empty schema with only the seeded shifts + super admin."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_defaults(db)
    limiter.reset()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def _login(client: TestClient, email: str, password: str) -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin_headers(client):
    tokens = _login(client, "admin@example.com", "Admin@12345")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def admin(client, admin_headers) -> Api:
    return Api(client, admin_headers)


@pytest.fixture
def make_user(client, admin):
    """make_user("quality_manager") -> Api acting as a freshly created user with that role."""
    counter = {"n": 0}

    def _make(role: str, password: str = "Passw0rd!x") -> Api:
        counter["n"] += 1
        email = f"{role}{counter['n']}@example.com"
        created = admin.post("/users", {"email": email, "full_name": f"Test {role}", "password": password, "role": role}, expect=201)
        tokens = _login(client, email, password)
        api = Api(client, {"Authorization": f"Bearer {tokens['access_token']}"})
        api.user = created
        api.email, api.password = email, password
        return api

    return _make
