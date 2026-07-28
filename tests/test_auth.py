"""Tests for src.auth and the auth guard in src.web."""
import pytest
from fastapi.testclient import TestClient

from src import storage
from src.auth import (
    SESSION_COOKIE,
    authenticate,
    ensure_default_admin,
    hash_password,
    verify_password,
)
from src.web import app


@pytest.fixture
def auth_db(tmp_path, monkeypatch):
    """Isolated temp database with the built-in admin seeded."""
    db_file = tmp_path / "auth_test.db"
    monkeypatch.setattr("src.storage.DATABASE_URL", f"sqlite:///{db_file}")
    storage.init_db()
    ensure_default_admin()
    return db_file


@pytest.fixture
def admin_client(auth_db):
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login", json={"username": "gsadmin", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    return client


def _login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


# ====== Password hashing ======

def test_password_hash_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed.startswith("pbkdf2$")
    assert "s3cret!" not in hashed
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_password_rejects_malformed_hash():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "bcrypt$1$2$3")


# ====== Built-in admin seeding ======

def test_default_admin_seeded_once(auth_db):
    assert authenticate("gsadmin", "admin123") == {
        "username": "gsadmin",
        "role": "admin",
    }
    # Second call must not duplicate or fail.
    ensure_default_admin()
    assert storage.count_users() == 1


def test_authenticate_rejects_bad_credentials(auth_db):
    assert authenticate("gsadmin", "wrong") is None
    assert authenticate("nobody", "admin123") is None


# ====== Login / logout / session ======

def test_login_success_sets_cookie_and_me(auth_db):
    client = TestClient(app)
    resp = _login(client, "gsadmin", "admin123")
    assert resp.status_code == 200
    assert resp.json() == {"username": "gsadmin", "role": "admin"}
    assert SESSION_COOKIE in resp.cookies
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "gsadmin"


def test_login_wrong_password_returns_401(auth_db):
    client = TestClient(app)
    resp = _login(client, "gsadmin", "nope")
    assert resp.status_code == 401
    assert "用户名或密码错误" in resp.json()["detail"]


def test_login_missing_fields_returns_422(auth_db):
    client = TestClient(app)
    assert client.post("/api/auth/login", json={}).status_code == 422


def test_logout_invalidates_session(admin_client):
    assert admin_client.get("/api/auth/me").status_code == 200
    admin_client.post("/api/auth/logout")
    assert admin_client.get("/api/auth/me").status_code == 401


# ====== Auth guard middleware ======

def test_unauthenticated_api_returns_401(auth_db):
    client = TestClient(app)
    for path in ("/api/reports", "/api/signals/recent", "/api/settings",
                 "/api/auth/me", "/api/pipeline/status"):
        resp = client.get(path)
        assert resp.status_code == 401, path
        assert "未登录" in resp.json()["detail"]


def test_unauthenticated_page_redirects_to_login(auth_db):
    client = TestClient(app)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_page_is_public(auth_db):
    client = TestClient(app)
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "登录" in resp.text


def test_health_is_public(auth_db):
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


# ====== Role-based access ======

@pytest.fixture
def viewer_client(admin_client):
    admin_client.post(
        "/api/settings/users",
        json={"username": "bob", "password": "bobpass", "role": "viewer"},
    )
    client = TestClient(app)
    resp = _login(client, "bob", "bobpass")
    assert resp.status_code == 200, resp.text
    return client


def test_viewer_can_use_non_settings_apis(viewer_client):
    assert viewer_client.get("/api/auth/me").json()["role"] == "viewer"
    assert viewer_client.get("/api/reports").status_code == 200
    assert viewer_client.get("/api/pipeline/status").status_code == 200
    assert viewer_client.get("/", follow_redirects=False).status_code == 200


def test_viewer_forbidden_from_settings(viewer_client):
    for path in ("/api/settings", "/api/settings/sources",
                 "/api/settings/llm-models", "/api/settings/users"):
        resp = viewer_client.get(path)
        assert resp.status_code == 403, path
        assert "管理员" in resp.json()["detail"]
    # Writes are blocked too.
    assert viewer_client.put("/api/settings", json={}).status_code == 403
    assert viewer_client.post(
        "/api/settings/users",
        json={"username": "x", "password": "y", "role": "viewer"},
    ).status_code == 403


def test_admin_can_access_settings(admin_client):
    assert admin_client.get("/api/settings").status_code == 200
    assert admin_client.get("/api/settings/users").status_code == 200


# ====== User management ======

def test_create_and_list_users(admin_client):
    resp = admin_client.post(
        "/api/settings/users",
        json={"username": "alice", "password": "alicepw", "role": "admin"},
    )
    assert resp.status_code == 201
    users = admin_client.get("/api/settings/users").json()
    names = {u["username"]: u["role"] for u in users}
    assert names == {"gsadmin": "admin", "alice": "admin"}
    assert all("password" not in u for u in users)


def test_create_user_validation(admin_client):
    # Missing fields
    assert admin_client.post(
        "/api/settings/users", json={"username": "", "password": "x"}
    ).status_code == 422
    # Bad role
    assert admin_client.post(
        "/api/settings/users",
        json={"username": "x", "password": "y", "role": "superuser"},
    ).status_code == 422
    # Duplicate
    admin_client.post(
        "/api/settings/users",
        json={"username": "dup", "password": "p", "role": "viewer"},
    )
    assert admin_client.post(
        "/api/settings/users",
        json={"username": "dup", "password": "p", "role": "viewer"},
    ).status_code == 409


def test_new_user_can_login(admin_client, auth_db):
    admin_client.post(
        "/api/settings/users",
        json={"username": "carol", "password": "carolpw", "role": "viewer"},
    )
    client = TestClient(app)
    resp = _login(client, "carol", "carolpw")
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


def test_update_password_invalidates_old_session(admin_client, auth_db):
    admin_client.post(
        "/api/settings/users",
        json={"username": "dave", "password": "oldpw", "role": "viewer"},
    )
    dave = TestClient(app)
    assert _login(dave, "dave", "oldpw").status_code == 200
    resp = admin_client.put("/api/settings/users/dave", json={"password": "newpw"})
    assert resp.status_code == 200
    # Old session is dead, old password rejected, new password works.
    assert dave.get("/api/auth/me").status_code == 401
    assert _login(TestClient(app), "dave", "oldpw").status_code == 401
    assert _login(TestClient(app), "dave", "newpw").status_code == 200


def test_update_user_role(admin_client):
    admin_client.post(
        "/api/settings/users",
        json={"username": "erin", "password": "pw", "role": "viewer"},
    )
    resp = admin_client.put("/api/settings/users/erin", json={"role": "admin"})
    assert resp.status_code == 200
    assert storage.get_user("erin")["role"] == "admin"
    assert admin_client.put(
        "/api/settings/users/erin", json={"role": "bogus"}
    ).status_code == 422
    assert admin_client.put(
        "/api/settings/users/ghost", json={"role": "admin"}
    ).status_code == 404


def test_gsadmin_protections(admin_client):
    # Cannot delete the built-in admin.
    assert admin_client.delete("/api/settings/users/gsadmin").status_code == 422
    # Cannot demote the built-in admin.
    assert admin_client.put(
        "/api/settings/users/gsadmin", json={"role": "viewer"}
    ).status_code == 422
    # Password change is allowed.
    assert admin_client.put(
        "/api/settings/users/gsadmin", json={"password": "admin123"}
    ).status_code == 200


def test_delete_user(admin_client):
    admin_client.post(
        "/api/settings/users",
        json={"username": "fred", "password": "pw", "role": "viewer"},
    )
    assert admin_client.delete("/api/settings/users/fred").status_code == 200
    assert storage.get_user("fred") is None
    assert admin_client.delete("/api/settings/users/fred").status_code == 404


def test_cannot_delete_self(admin_client):
    resp = admin_client.delete("/api/settings/users/gsadmin")
    assert resp.status_code == 422  # gsadmin guard triggers first


def test_deleted_user_session_dies(admin_client, auth_db):
    admin_client.post(
        "/api/settings/users",
        json={"username": "gina", "password": "pw", "role": "viewer"},
    )
    gina = TestClient(app)
    assert _login(gina, "gina", "pw").status_code == 200
    admin_client.delete("/api/settings/users/gina")
    assert gina.get("/api/auth/me").status_code == 401
