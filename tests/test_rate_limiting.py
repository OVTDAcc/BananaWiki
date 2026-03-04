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


def test_rl_store_key_retained_when_blocked_with_live_timestamps(app_mod):
    """When rate-limited with active timestamps, the key must stay in _RL_STORE."""
    ip, bucket, max_req = "10.0.0.1", "bucket_retain", 3
    for _ in range(max_req):
        app_mod._rl_check(ip, bucket, max_req, 60)
    key = (ip, bucket)
    assert key in app_mod._RL_STORE
    # Trigger the blocked path — key must still be in store afterwards
    result = app_mod._rl_check(ip, bucket, max_req, 60)
    assert result is False
    assert key in app_mod._RL_STORE
    assert len(app_mod._RL_STORE[key]) == max_req


def test_rl_store_key_not_stored_when_max_requests_zero(app_mod):
    """When max_requests=0 every call is immediately blocked; no key should linger."""
    ip, bucket = "10.0.0.2", "bucket_zero"
    key = (ip, bucket)
    # Should be blocked on first call and key must NOT be stored
    result = app_mod._rl_check(ip, bucket, 0, 60)
    assert result is False
    assert key not in app_mod._RL_STORE


def test_rl_store_stale_timestamps_replaced_on_return(app_mod, monkeypatch):
    """After the rate-limit window expires, returning IPs start a fresh counter."""
    from datetime import datetime, timezone

    ip, bucket, max_req, window = "10.0.0.3", "bucket_stale", 3, 60

    # Record max_req requests at time T
    fake_past = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "helpers._rate_limiting.datetime",
        type("FakeDT", (), {
            "now": staticmethod(lambda tz=None: fake_past),
        }),
    )
    for _ in range(max_req):
        app_mod._rl_check(ip, bucket, max_req, window)

    key = (ip, bucket)
    assert key in app_mod._RL_STORE
    assert len(app_mod._RL_STORE[key]) == max_req

    # Advance time beyond the window — all stored timestamps are now expired
    monkeypatch.undo()  # restore real datetime
    # The IP makes a new request; pruning removes stale timestamps and adds the new one
    result = app_mod._rl_check(ip, bucket, max_req, window)
    assert result is True
    assert key in app_mod._RL_STORE
    # Only the new timestamp should remain (all old ones were outside the window)
    assert len(app_mod._RL_STORE[key]) == 1


def test_rl_store_lock_used_for_all_operations(app_mod):
    """_rl_check acquires _RL_LOCK; concurrent calls must not corrupt _RL_STORE."""
    import threading

    results = []
    ip, bucket, max_req, window = "10.0.0.4", "bucket_threads", 100, 60

    def make_request():
        results.append(app_mod._rl_check(ip, bucket, max_req, window))

    threads = [threading.Thread(target=make_request) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 50 requests should be allowed (well under max_req=100)
    assert all(results)
    key = (ip, bucket)
    # Exactly 50 timestamps should be stored (no double-counting or lost writes)
    assert len(app_mod._RL_STORE[key]) == 50


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


# -----------------------------------------------------------------------
# Stale key cleanup: expired timestamps are evicted from _RL_STORE
# -----------------------------------------------------------------------
def test_rl_store_stale_key_cleaned_up_when_all_timestamps_expired(
    app_mod, monkeypatch
):
    """After the window expires, a new request removes the old key then re-adds it.

    _rl_check must pop the stale key before re-inserting so that memory is
    not permanently accumulated by IPs that get rate-limited and go quiet.
    """
    from datetime import datetime, timezone

    ip, bucket, max_req, window = "10.0.1.1", "bucket_cleanup", 3, 60

    # Fill the bucket to the limit at time T in the past.
    fake_past = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "helpers._rate_limiting.datetime",
        type("FakeDT", (), {
            "now": staticmethod(lambda tz=None: fake_past),
        }),
    )
    for _ in range(max_req):
        app_mod._rl_check(ip, bucket, max_req, window)

    key = (ip, bucket)
    assert key in app_mod._RL_STORE
    stale_timestamps = list(app_mod._RL_STORE[key])

    # Advance time so all timestamps have expired.
    monkeypatch.undo()
    # First new request: stale key is evicted, fresh counter starts with just 1.
    result = app_mod._rl_check(ip, bucket, max_req, window)
    assert result is True
    # The stored timestamps must NOT contain any of the old stale ones.
    fresh_timestamps = app_mod._RL_STORE[key]
    assert not any(t in stale_timestamps for t in fresh_timestamps), (
        "Stale timestamps should have been pruned and not remain in _RL_STORE"
    )
    assert len(fresh_timestamps) == 1


def test_rl_store_key_removed_after_window_expiry_on_blocked_path(
    app_mod, monkeypatch
):
    """When max_requests=0 a request blocked with empty pruned list does not
    leave an empty list in _RL_STORE (verifies the dead-code fix)."""
    ip, bucket = "10.0.1.2", "bucket_dead_code"
    key = (ip, bucket)
    # Calling with max_requests=0 means every request is immediately blocked.
    result = app_mod._rl_check(ip, bucket, 0, 60)
    assert result is False
    # No entry (not even an empty list) must be stored.
    assert key not in app_mod._RL_STORE
