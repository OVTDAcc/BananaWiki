"""
Tests for BananaWiki rate limiting.
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
    """Clear the in-memory rate limit store before and after each test."""
    import app as app_mod
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    yield
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()


@pytest.fixture
def app_mod():
    """Return the app module (shared import for tests that need _RL_STORE)."""
    import app as _app_mod
    return _app_mod


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_user():
    """Create an admin user and mark setup as done."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Return a client logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# -----------------------------------------------------------------------
# _rl_check unit tests
# -----------------------------------------------------------------------
def test_rl_check_allows_within_limit():
    from app import _rl_check
    for _ in range(5):
        assert _rl_check("1.2.3.4", "bucket_a", 5, 60) is True


def test_rl_check_blocks_over_limit():
    from app import _rl_check
    for _ in range(5):
        _rl_check("1.2.3.4", "bucket_b", 5, 60)
    assert _rl_check("1.2.3.4", "bucket_b", 5, 60) is False


def test_rl_check_different_ips_are_independent():
    from app import _rl_check
    for _ in range(5):
        _rl_check("1.2.3.4", "bucket_c", 5, 60)
    # A different IP should have its own independent counter
    assert _rl_check("5.6.7.8", "bucket_c", 5, 60) is True


def test_rl_check_different_buckets_are_independent():
    from app import _rl_check
    for _ in range(5):
        _rl_check("1.2.3.4", "bucket_d1", 5, 60)
    # A different bucket for the same IP should be independent
    assert _rl_check("1.2.3.4", "bucket_d2", 5, 60) is True


# -----------------------------------------------------------------------
# Memory-leak fix: _RL_STORE should not accumulate stale keys
# -----------------------------------------------------------------------
def test_rl_store_no_key_created_on_first_read(app_mod):
    """A new (ip, bucket) key must not appear in _RL_STORE just from checking."""
    key = ("9.9.9.9", "bucket_new")
    assert key not in app_mod._RL_STORE
    # Record one real request; only then should the key be created
    app_mod._rl_check("9.9.9.9", "bucket_new", 5, 60)
    assert key in app_mod._RL_STORE
    assert len(app_mod._RL_STORE[key]) == 1


def test_rl_store_plain_dict_not_defaultdict(app_mod):
    """_RL_STORE must be a plain dict so missing keys don't auto-create."""
    from collections import defaultdict
    assert not isinstance(app_mod._RL_STORE, defaultdict), (
        "_RL_STORE should be a plain dict, not a defaultdict"
    )


# -----------------------------------------------------------------------
# Signup rate limit
# -----------------------------------------------------------------------
def test_signup_rate_limited(client, admin_user):
    """Signup endpoint returns 429 after exceeding the per-IP limit."""
    for _ in range(10):
        client.post("/signup", data={
            "username": "user", "password": "pass",
            "confirm_password": "pass", "invite_code": "INVALID",
        })
    resp = client.post("/signup", data={
        "username": "user", "password": "pass",
        "confirm_password": "pass", "invite_code": "INVALID",
    })
    assert resp.status_code == 429
    assert b"Too Many Requests" in resp.data


# -----------------------------------------------------------------------
# API endpoint rate limits (JSON responses)
# -----------------------------------------------------------------------
def test_api_preview_rate_limited(logged_in_admin):
    """API preview endpoint returns JSON 429 after exceeding the limit."""
    for _ in range(30):
        logged_in_admin.post(
            "/api/preview",
            json={"content": "test"},
            content_type="application/json",
        )
    resp = logged_in_admin.post(
        "/api/preview",
        json={"content": "test"},
        content_type="application/json",
    )
    assert resp.status_code == 429
    data = resp.get_json()
    assert data is not None
    assert "error" in data


def test_upload_rate_limited(logged_in_admin):
    """Upload endpoint returns JSON 429 after exceeding the limit."""
    for _ in range(10):
        logged_in_admin.post(
            "/api/upload",
            data={},
            content_type="multipart/form-data",
        )
    resp = logged_in_admin.post(
        "/api/upload",
        data={},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 429
    data = resp.get_json()
    assert data is not None
    assert "error" in data


# -----------------------------------------------------------------------
# Global rate limit
# -----------------------------------------------------------------------
def test_global_rate_limit(client, admin_user, monkeypatch):
    """All non-static endpoints are blocked after hitting the global limit."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_RL_GLOBAL_MAX", 3)
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    for _ in range(3):
        client.get("/login")
    resp = client.get("/login")
    assert resp.status_code == 429
    assert b"Too Many Requests" in resp.data


def test_global_rate_limit_json_response(client, admin_user, monkeypatch):
    """Global rate limit on API paths returns JSON 429."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_RL_GLOBAL_MAX", 1)
    # Log in first (this consumes 1 request toward global)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    # Use one request
    client.get("/login")
    # Next request to an API path should be rate-limited with JSON
    resp = client.post(
        "/api/preview",
        json={"content": "test"},
        content_type="application/json",
    )
    assert resp.status_code == 429
    data = resp.get_json()
    assert data is not None
    assert "error" in data


def test_global_rate_limit_logged_in_user_renders_429(logged_in_admin, monkeypatch):
    """Global rate limit renders 429 page correctly for a logged-in user (sidebar uses categories)."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_RL_GLOBAL_MAX", 1)
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    logged_in_admin.get("/")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 429
    assert b"Too Many Requests" in resp.data


# -----------------------------------------------------------------------
# 429 error handler
# -----------------------------------------------------------------------
def test_429_error_handler(client, admin_user, monkeypatch):
    """The 429 error handler renders the 429 template."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_RL_GLOBAL_MAX", 1)
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    client.get("/login")
    resp = client.get("/login")
    assert resp.status_code == 429
    assert b"429" in resp.data
