"""
Tests for BananaWiki bug fixes and edge cases.
"""

import os
import sys
import tempfile
import pytest

# Ensure the project root is importable
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
    """Return a client that is logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# -----------------------------------------------------------------------
# Fix 1: account_settings should render without errors (sidebar data)
# -----------------------------------------------------------------------
def test_account_settings_renders(logged_in_admin):
    resp = logged_in_admin.get("/account")
    assert resp.status_code == 200
    assert b"Account Settings" in resp.data


# -----------------------------------------------------------------------
# Fix 2: 404 page should render without errors (sidebar data)
# -----------------------------------------------------------------------
def test_404_renders(logged_in_admin):
    resp = logged_in_admin.get("/page/nonexistent-slug")
    assert resp.status_code == 404
    assert b"Page Not Found" in resp.data


# -----------------------------------------------------------------------
# Fix 3: Home page should include editor_info after editing
# -----------------------------------------------------------------------
def test_home_page_shows_editor_info(logged_in_admin):
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated content", 1, "test edit")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"Last edit by" in resp.data
    assert b"admin" in resp.data


# -----------------------------------------------------------------------
# Fix 4: slugify with special characters should not produce empty slug
# -----------------------------------------------------------------------
def test_slugify_empty_input():
    from app import slugify
    assert slugify("") == "page"
    assert slugify("!!!") == "page"
    assert slugify("   ") == "page"
    assert slugify("hello world") == "hello-world"
    assert slugify("Test Page!") == "test-page"


# -----------------------------------------------------------------------
# Fix 5: api_delete_draft validates page_id
# -----------------------------------------------------------------------
def test_api_delete_draft_validates_page_id(logged_in_admin):
    # Missing page_id
    resp = logged_in_admin.post("/api/draft/delete",
                                json={},
                                content_type="application/json")
    assert resp.status_code == 400

    # Invalid page_id
    resp = logged_in_admin.post("/api/draft/delete",
                                json={"page_id": "abc"},
                                content_type="application/json")
    assert resp.status_code == 400


# -----------------------------------------------------------------------
# Fix 6: Admin cannot suspend or delete themselves via admin panel
# -----------------------------------------------------------------------
def test_admin_cannot_suspend_self(logged_in_admin, admin_user):
    resp = logged_in_admin.post(f"/admin/users/{admin_user}/edit",
                                data={"action": "suspend"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot suspend your own account" in resp.data


def test_admin_cannot_delete_self(logged_in_admin, admin_user):
    resp = logged_in_admin.post(f"/admin/users/{admin_user}/edit",
                                data={"action": "delete"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot delete your own account" in resp.data


# -----------------------------------------------------------------------
# Fix 7: update_page_title records history
# -----------------------------------------------------------------------
def test_edit_title_records_history(logged_in_admin):
    import db
    home = db.get_home_page()
    slug = home["slug"]
    resp = logged_in_admin.post(f"/page/{slug}/edit/title",
                                data={"title": "New Home Title"},
                                follow_redirects=True)
    assert resp.status_code == 200
    history = db.get_page_history(home["id"])
    assert len(history) > 0
    assert any("Title changed" in (h["edit_message"] or "") for h in history)


# -----------------------------------------------------------------------
# Fix 8: Admin settings validates color inputs
# -----------------------------------------------------------------------
def test_admin_settings_rejects_invalid_color(logged_in_admin):
    resp = logged_in_admin.post("/admin/settings", data={
        "site_name": "TestWiki",
        "primary_color": "not-a-color",
        "secondary_color": "#151520",
        "accent_color": "#6e8aca",
        "text_color": "#b8bcc8",
        "sidebar_color": "#111118",
        "bg_color": "#0d0d14",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid color" in resp.data


def test_admin_settings_accepts_valid_colors(logged_in_admin):
    resp = logged_in_admin.post("/admin/settings", data={
        "site_name": "MyWiki",
        "primary_color": "#aabbcc",
        "secondary_color": "#112233",
        "accent_color": "#445566",
        "text_color": "#778899",
        "sidebar_color": "#001122",
        "bg_color": "#334455",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Settings updated" in resp.data
