"""
Tests for API token generation, usage, and revocation.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
    import app as app_mod
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    yield
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def regular_user():
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("alice", generate_password_hash("pass123"), role="user")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def admin_user():
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def logged_in_user(client, regular_user):
    client.post("/login", data={"username": "alice", "password": "pass123"})
    return client


@pytest.fixture
def logged_in_admin(client, admin_user):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

class TestApiTokenDb:
    def test_create_and_lookup(self, regular_user):
        import db
        token = db.create_api_token(regular_user, "my script")
        assert len(token) == 64  # 32 bytes → 64 hex chars
        row = db.get_api_token_by_value(token)
        assert row is not None
        assert row["user_id"] == regular_user
        assert row["name"] == "my script"
        assert row["last_used_at"] is None

    def test_list_tokens(self, regular_user):
        import db
        db.create_api_token(regular_user, "token A")
        db.create_api_token(regular_user, "token B")
        tokens = db.list_user_api_tokens(regular_user)
        assert len(tokens) == 2
        names = {t["name"] for t in tokens}
        assert names == {"token A", "token B"}
        # Sensitive token value is NOT returned by list
        for tok in tokens:
            assert "token" not in tok.keys()

    def test_revoke(self, regular_user):
        import db
        token = db.create_api_token(regular_user, "disposable")
        row = db.get_api_token_by_value(token)
        result = db.revoke_api_token(row["id"], regular_user)
        assert result is True
        assert db.get_api_token_by_value(token) is None

    def test_revoke_wrong_user(self, regular_user):
        from werkzeug.security import generate_password_hash
        import db
        other_uid = db.create_user("bob", generate_password_hash("x"), role="user")
        token = db.create_api_token(regular_user, "mine")
        row = db.get_api_token_by_value(token)
        result = db.revoke_api_token(row["id"], other_uid)
        assert result is False
        assert db.get_api_token_by_value(token) is not None

    def test_update_last_used(self, regular_user):
        import db
        token = db.create_api_token(regular_user, "track me")
        row = db.get_api_token_by_value(token)
        db.update_token_last_used(row["id"])
        updated = db.get_api_token_by_value(token)
        assert updated["last_used_at"] is not None

    def test_revoke_all(self, regular_user):
        import db
        db.create_api_token(regular_user, "t1")
        db.create_api_token(regular_user, "t2")
        db.revoke_all_user_api_tokens(regular_user)
        assert db.list_user_api_tokens(regular_user) == []

    def test_token_deleted_with_user(self, regular_user):
        import db
        token = db.create_api_token(regular_user, "orphan")
        db.delete_user(regular_user)
        assert db.get_api_token_by_value(token) is None


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

class TestGetUserFromApiToken:
    def test_returns_user_for_valid_token(self, regular_user):
        import db
        from helpers import get_user_from_api_token
        from app import app
        token = db.create_api_token(regular_user, "helper test")
        with app.test_request_context(
            "/", headers={"Authorization": f"Bearer {token}"}
        ):
            user = get_user_from_api_token()
        assert user is not None
        assert user["id"] == regular_user

    def test_returns_none_for_bad_token(self, regular_user):
        from helpers import get_user_from_api_token
        from app import app
        with app.test_request_context(
            "/", headers={"Authorization": "Bearer invalidtoken"}
        ):
            user = get_user_from_api_token()
        assert user is None

    def test_accepts_query_param(self, regular_user):
        import db
        from helpers import get_user_from_api_token
        from app import app
        token = db.create_api_token(regular_user, "qp test")
        with app.test_request_context(f"/?token={token}"):
            user = get_user_from_api_token()
        assert user is not None
        assert user["id"] == regular_user

    def test_suspended_user_rejected(self, regular_user):
        import db
        from helpers import get_user_from_api_token
        from app import app
        token = db.create_api_token(regular_user, "sus test")
        db.update_user(regular_user, suspended=1)
        with app.test_request_context(
            "/", headers={"Authorization": f"Bearer {token}"}
        ):
            user = get_user_from_api_token()
        assert user is None


# ---------------------------------------------------------------------------
# Public API v1 routes
# ---------------------------------------------------------------------------

class TestApiV1Routes:
    def test_list_pages_public(self, client, regular_user):
        import db
        db.create_page("Test Page", "test-page", "Hello world")
        resp = client.get("/api/v1/pages")
        assert resp.status_code == 200
        data = resp.get_json()
        slugs = [p["slug"] for p in data]
        assert "test-page" in slugs
        # home page excluded
        assert "home" not in slugs

    def test_list_pages_excludes_deindexed_for_anonymous(self, client, admin_user):
        import db
        page = db.create_page("Secret", "secret-page", "hidden")
        db.set_page_deindexed(page, True)
        resp = client.get("/api/v1/pages")
        assert resp.status_code == 200
        slugs = [p["slug"] for p in resp.get_json()]
        assert "secret-page" not in slugs

    def test_list_pages_includes_deindexed_for_editor(self, client, admin_user):
        import db
        page = db.create_page("Secret", "secret-page", "hidden")
        db.set_page_deindexed(page, True)
        token = db.create_api_token(admin_user, "editor token")
        resp = client.get(f"/api/v1/pages?token={token}")
        assert resp.status_code == 200
        slugs = [p["slug"] for p in resp.get_json()]
        assert "secret-page" in slugs

    def test_get_page_by_slug(self, client, regular_user):
        import db
        db.create_page("About", "about", "About page content")
        resp = client.get("/api/v1/pages/about")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["slug"] == "about"
        assert data["title"] == "About"
        assert "content" in data

    def test_get_page_not_found(self, client, regular_user):
        resp = client.get("/api/v1/pages/does-not-exist")
        assert resp.status_code == 404
        assert resp.get_json()["error"] == "page not found"

    def test_get_deindexed_page_requires_auth(self, client, admin_user):
        import db
        page = db.create_page("Hidden", "hidden-page", "secret")
        db.set_page_deindexed(page, True)
        # anonymous
        resp = client.get("/api/v1/pages/hidden-page")
        assert resp.status_code == 404
        # with valid token
        token = db.create_api_token(admin_user, "auth test")
        resp = client.get(f"/api/v1/pages/hidden-page?token={token}")
        assert resp.status_code == 200

    def test_search(self, client, regular_user):
        import db
        db.create_page("Banana Facts", "banana-facts", "Bananas are yellow")
        resp = client.get("/api/v1/search?q=Banana")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(p["slug"] == "banana-facts" for p in data)

    def test_search_empty_query(self, client, regular_user):
        resp = client.get("/api/v1/search")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_categories(self, client, regular_user):
        import db
        db.create_category("Tutorials")
        resp = client.get("/api/v1/categories")
        assert resp.status_code == 200
        data = resp.get_json()
        assert any(c["name"] == "Tutorials" for c in data)

    def test_me_requires_auth(self, client, regular_user):
        resp = client.get("/api/v1/me")
        assert resp.status_code == 401

    def test_me_with_token(self, client, regular_user):
        import db
        token = db.create_api_token(regular_user, "me test")
        resp = client.get(f"/api/v1/me?token={token}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["username"] == "alice"
        assert data["role"] == "user"

    def test_me_with_bearer_header(self, client, regular_user):
        import db
        token = db.create_api_token(regular_user, "bearer test")
        resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.get_json()["username"] == "alice"


# ---------------------------------------------------------------------------
# Token management web routes
# ---------------------------------------------------------------------------

class TestTokenManagementRoutes:
    def test_create_token_route(self, logged_in_user, regular_user):
        import db
        resp = logged_in_user.post(
            "/account/tokens/create",
            data={"name": "my token"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        tokens = db.list_user_api_tokens(regular_user)
        assert len(tokens) == 1
        assert tokens[0]["name"] == "my token"
        # Flash message contains the token value
        assert b"Copy it now" in resp.data

    def test_create_token_requires_name(self, logged_in_user, regular_user):
        import db
        resp = logged_in_user.post(
            "/account/tokens/create",
            data={"name": ""},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.list_user_api_tokens(regular_user) == []

    def test_revoke_token_route(self, logged_in_user, regular_user):
        import db
        db.create_api_token(regular_user, "to revoke")
        tokens = db.list_user_api_tokens(regular_user)
        token_id = tokens[0]["id"]
        resp = logged_in_user.post(
            "/account/tokens/revoke",
            data={"token_id": str(token_id)},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.list_user_api_tokens(regular_user) == []

    def test_account_page_shows_tokens(self, logged_in_user, regular_user):
        import db
        db.create_api_token(regular_user, "visible token")
        resp = logged_in_user.get("/account")
        assert resp.status_code == 200
        assert b"visible token" in resp.data
        assert b"API Tokens" in resp.data

    def test_max_tokens_enforced(self, logged_in_user, regular_user):
        import db
        for i in range(10):
            db.create_api_token(regular_user, f"token {i}")
        resp = logged_in_user.post(
            "/account/tokens/create",
            data={"name": "one too many"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.list_user_api_tokens(regular_user).__len__() == 10

    def test_api_doc_page_created(self):
        import db
        page = db.get_page_by_slug("api-documentation")
        assert page is not None
        assert page["title"] == "API Documentation"
        assert "/api/v1/" in page["content"]
