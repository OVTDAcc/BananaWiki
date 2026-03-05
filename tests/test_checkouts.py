"""
Tests for the page checkout / edit locking feature.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

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
    """Clear the in-memory rate-limit store before and after each test."""
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


def test_edit_page_acquires_checkout_and_blocks_other_editor(logged_in_admin, admin_user):
    """Opening edit page acquires checkout; other editors are redirected."""
    import db
    from werkzeug.security import generate_password_hash
    page_id = db.create_page("Checkout Page", "checkout-page", user_id=admin_user)

    resp = logged_in_admin.get("/page/checkout-page/edit")
    assert resp.status_code == 200
    checkout = db.get_checkout(page_id)
    assert checkout is not None
    assert checkout["user_id"] == admin_user

    editor_id = db.create_user("editor1", generate_password_hash("pw"), role="editor")
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c2:
        c2.post("/login", data={"username": "editor1", "password": "pw"})
        resp2 = c2.get("/page/checkout-page/edit", follow_redirects=False)
        assert resp2.status_code == 302
        assert "/page/checkout-page" in resp2.headers.get("Location", "")
        checkout_after = db.get_checkout(page_id)
        assert checkout_after["user_id"] == admin_user


def test_checkout_released_after_commit(logged_in_admin, admin_user):
    """Saving a page releases its checkout."""
    import db
    page_id = db.create_page("Commit Release", "commit-release", user_id=admin_user)
    logged_in_admin.get("/page/commit-release/edit")
    resp = logged_in_admin.post("/page/commit-release/edit", data={
        "title": "Commit Release",
        "content": "updated content",
        "edit_message": "saving",
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert db.get_checkout(page_id) is None


def test_checkout_timeout_allows_new_holder(logged_in_admin, admin_user):
    """Expired checkouts are cleaned up and can be re-acquired by another user."""
    import db
    from werkzeug.security import generate_password_hash
    page_id = db.create_page("Timeout Page", "timeout-page", user_id=admin_user)
    db.acquire_checkout(page_id, admin_user)

    # Age the checkout beyond the timeout window
    conn = db.get_db()
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    conn.execute("UPDATE page_checkouts SET last_seen=? WHERE page_id=?", (old_ts, page_id))
    conn.commit()
    conn.close()

    db.cleanup_expired_checkouts()

    editor_id = db.create_user("ed2", generate_password_hash("pw"), role="editor")
    checkout, acquired = db.acquire_checkout(page_id, editor_id)
    assert acquired is True
    assert checkout["user_id"] == editor_id


def test_admin_can_release_checkout(logged_in_admin, admin_user):
    """Admin panel can list and release active checkouts."""
    import db
    page_id = db.create_page("Admin Release", "admin-release", user_id=admin_user)
    logged_in_admin.get("/page/admin-release/edit")
    resp = logged_in_admin.get("/admin/checkouts")
    assert resp.status_code == 200
    assert b"admin-release" in resp.data

    resp = logged_in_admin.post("/admin/checkouts/release",
                                data={"page_id": page_id},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Checkout released" in resp.data or b"released" in resp.data.lower()
    assert db.get_checkout(page_id) is None
