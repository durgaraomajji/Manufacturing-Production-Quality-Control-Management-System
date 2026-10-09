"""The Swagger / OpenAPI document must be valid and describe the API's real behaviour."""
import pytest

PUBLIC = {("post", "/api/v1/auth/register"), ("post", "/api/v1/auth/login"), ("post", "/api/v1/auth/token"),
          ("post", "/api/v1/auth/refresh"), ("post", "/api/v1/auth/password-reset/request"),
          ("post", "/api/v1/auth/password-reset/confirm"), ("get", "/health")}


@pytest.fixture
def spec(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    return r.json()


def operations(spec):
    return [(m, p, o) for p, item in spec["paths"].items() for m, o in item.items() if m in ("get", "post", "put", "patch", "delete")]


def test_docs_pages_are_served(client):
    assert client.get("/docs").status_code == 200 and "swagger" in client.get("/docs").text.lower()
    assert client.get("/redoc").status_code == 200


def test_spec_is_valid_openapi(spec):
    validator = pytest.importorskip("openapi_spec_validator")
    validator.validate(spec)


def test_every_operation_is_documented(spec):
    ops = operations(spec)
    assert len(ops) > 100
    ids = [o["operationId"] for _, _, o in ops]
    assert len(ids) == len(set(ids))
    declared = {t["name"] for t in spec["tags"]}
    for m, p, o in ops:
        assert o.get("summary") and o.get("tags"), (m, p)
        assert set(o["tags"]) <= declared, (m, p)


def test_only_auth_entry_points_and_health_are_public(spec):
    public = {(m, p) for m, p, o in operations(spec) if not o.get("security")}
    assert public == PUBLIC
    assert spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/api/v1/auth/token"


def test_error_envelope_is_documented_accurately(spec, client):
    schemas = spec["components"]["schemas"]
    assert "ErrorResponse" in schemas and "HTTPValidationError" not in schemas
    for m, p, o in operations(spec):
        if "422" in o["responses"]:
            ref = o["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorResponse"), (m, p)
        if o.get("security"):
            assert {"401", "403"} <= set(o["responses"]), (m, p)
    body = client.post("/api/v1/auth/login", json={"email": "not-an-email"}).json()
    assert set(body) == {"error"} and {"code", "message"} <= set(body["error"])
