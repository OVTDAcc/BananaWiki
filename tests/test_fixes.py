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


# -----------------------------------------------------------------------
# Fix 9: time_ago handles future dates
# -----------------------------------------------------------------------
def test_time_ago_future_dates():
    from app import time_ago
    from datetime import datetime, timezone, timedelta
    future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
    result = time_ago(future)
    assert result.startswith("in ")
    assert "hour" in result

    far_future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    result = time_ago(far_future)
    assert result.startswith("in ")
    assert "day" in result


def test_time_ago_edge_cases():
    from app import time_ago
    assert time_ago(None) == "never"
    assert time_ago("") == "never"
    assert time_ago("not-a-date") == "unknown"


# -----------------------------------------------------------------------
# Fix 10: Admin rename user with invalid username shows error
# -----------------------------------------------------------------------
def test_admin_rename_user_short_username(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("testuser", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_username", "username": "ab"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Username must be at least 3 characters" in resp.data


def test_admin_rename_user_empty_username(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("testuser2", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_username", "username": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Username must be at least 3 characters" in resp.data


# -----------------------------------------------------------------------
# Fix 11: Create page with invalid category shows error
# -----------------------------------------------------------------------
def test_create_page_invalid_category(logged_in_admin):
    resp = logged_in_admin.post("/create-page",
                                data={"title": "Test Page", "content": "test",
                                      "category_id": "9999"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Selected category does not exist" in resp.data


# -----------------------------------------------------------------------
# Fix 12: Move page to invalid category shows error
# -----------------------------------------------------------------------
def test_move_page_invalid_category(logged_in_admin):
    import db
    db.create_page("Test Move", "test-move", "content", user_id=1)
    resp = logged_in_admin.post("/page/test-move/move",
                                data={"category_id": "9999"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Selected category does not exist" in resp.data


# -----------------------------------------------------------------------
# Fix 13: Signup handles IntegrityError gracefully
# -----------------------------------------------------------------------
def test_signup_duplicate_username_race(client, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    # Generate a valid invite code
    code = db.generate_invite_code(admin_user)
    # Pre-create the user to simulate a race
    db.create_user("raceuser", generate_password_hash("pass123"))

    resp = client.post("/signup", data={
        "username": "raceuser",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"already taken" in resp.data


# -----------------------------------------------------------------------
# Fix 14: Admin create user handles IntegrityError gracefully
# -----------------------------------------------------------------------
def test_admin_create_user_duplicate(logged_in_admin, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("dupuser", generate_password_hash("pass123"))

    resp = logged_in_admin.post("/admin/users/create", data={
        "username": "dupuser",
        "password": "password123",
        "confirm_password": "password123",
        "role": "user",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"already taken" in resp.data


# -----------------------------------------------------------------------
# Fix 15: Create page with non-numeric category_id doesn't crash
# -----------------------------------------------------------------------
def test_create_page_nonnumeric_category(logged_in_admin):
    resp = logged_in_admin.post("/create-page",
                                data={"title": "Test Page", "content": "test",
                                      "category_id": "abc"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid category" in resp.data


# -----------------------------------------------------------------------
# Fix 16: Move page with non-numeric category_id doesn't crash
# -----------------------------------------------------------------------
def test_move_page_nonnumeric_category(logged_in_admin):
    import db
    db.create_page("Test Move2", "test-move2", "content", user_id=1)
    resp = logged_in_admin.post("/page/test-move2/move",
                                data={"category_id": "abc"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid category" in resp.data


# -----------------------------------------------------------------------
# Fix 17: Create category with non-numeric parent_id doesn't crash
# -----------------------------------------------------------------------
def test_create_category_nonnumeric_parent(logged_in_admin):
    resp = logged_in_admin.post("/category/create",
                                data={"name": "TestCat", "parent_id": "abc"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid parent category" in resp.data


# -----------------------------------------------------------------------
# Fix 18: Admin settings rejects overly long site name
# -----------------------------------------------------------------------
def test_admin_settings_rejects_long_site_name(logged_in_admin):
    resp = logged_in_admin.post("/admin/settings", data={
        "site_name": "A" * 101,
        "primary_color": "#aabbcc",
        "secondary_color": "#112233",
        "accent_color": "#445566",
        "text_color": "#778899",
        "sidebar_color": "#001122",
        "bg_color": "#334455",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"100 characters" in resp.data


# -----------------------------------------------------------------------
# Fix 19: Admin cannot demote the last admin (self)
# -----------------------------------------------------------------------
def test_admin_cannot_demote_last_admin(logged_in_admin, admin_user):
    resp = logged_in_admin.post(f"/admin/users/{admin_user}/edit",
                                data={"action": "change_role", "role": "user"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot demote the last admin" in resp.data


# -----------------------------------------------------------------------
# Fix 20: Move page to uncategorized (empty category_id) works
# -----------------------------------------------------------------------
def test_move_page_to_uncategorized(logged_in_admin):
    import db
    cat_id = db.create_category("TempCat")
    db.create_page("TestMove3", "test-move3", "content", category_id=cat_id, user_id=1)
    resp = logged_in_admin.post("/page/test-move3/move",
                                data={"category_id": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Page moved" in resp.data
    page = db.get_page_by_slug("test-move3")
    assert page["category_id"] is None


# -----------------------------------------------------------------------
# Fix 21: Signup with empty invite code shows error
# -----------------------------------------------------------------------
def test_signup_empty_invite_code(client, admin_user):
    resp = client.post("/signup", data={
        "username": "newuser",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": "",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"All fields are required" in resp.data


# -----------------------------------------------------------------------
# Fix 22: Login with empty fields shows error
# -----------------------------------------------------------------------
def test_login_empty_fields(client, admin_user):
    resp = client.post("/login", data={
        "username": "",
        "password": "password123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid username or password" in resp.data


# -----------------------------------------------------------------------
# Fix 23: Deleting last admin account from account settings is blocked
# -----------------------------------------------------------------------
def test_last_admin_cannot_delete_own_account(logged_in_admin, admin_user):
    resp = logged_in_admin.post("/account",
                                data={"action": "delete_account", "password": "admin123"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot delete the last admin" in resp.data


# -----------------------------------------------------------------------
# Fix 24: Deleting a user who used an invite code does not crash
# -----------------------------------------------------------------------
def test_delete_user_with_invite_code(logged_in_admin, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    code = db.generate_invite_code(admin_user)
    uid = db.create_user("inviteduser", generate_password_hash("pass123"))
    db.use_invite_code(code, uid)
    # Admin deletes the user via the admin panel
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "delete"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"User deleted" in resp.data
    assert db.get_user_by_id(uid) is None


def test_self_delete_account_with_invite_code(client, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    # Create a second admin so the first can stay
    db.create_user("admin2", generate_password_hash("admin123"), role="admin")
    code = db.generate_invite_code(admin_user)
    uid = db.create_user("selfdeleter", generate_password_hash("pass123"))
    db.use_invite_code(code, uid)
    # Log in as the regular user
    client.post("/login", data={"username": "selfdeleter", "password": "pass123"})
    resp = client.post("/account",
                       data={"action": "delete_account", "password": "pass123"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"Your account has been deleted" in resp.data
    assert db.get_user_by_id(uid) is None


# -----------------------------------------------------------------------
# Fix 25: Page history routes return 404 when disabled (default)
# -----------------------------------------------------------------------
def test_page_history_disabled_by_default(logged_in_admin):
    import config
    assert config.PAGE_HISTORY_ENABLED is False
    resp = logged_in_admin.get("/page/home/history")
    assert resp.status_code == 404


def test_page_history_entry_disabled_by_default(logged_in_admin):
    resp = logged_in_admin.get("/page/home/history/1")
    assert resp.status_code == 404


def test_page_revert_disabled_by_default(logged_in_admin):
    resp = logged_in_admin.post("/page/home/revert/1")
    assert resp.status_code == 404


def test_page_history_enabled(logged_in_admin, monkeypatch):
    import config
    monkeypatch.setattr(config, "PAGE_HISTORY_ENABLED", True)
    resp = logged_in_admin.get("/page/home/history")
    assert resp.status_code == 200


# -----------------------------------------------------------------------
# Fix 26: Editors cannot access invite codes pages
# -----------------------------------------------------------------------
def test_editor_cannot_access_invite_codes(client, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    client.post("/login", data={"username": "editor1", "password": "pass123"})
    resp = client.get("/admin/codes", follow_redirects=True)
    assert b"Admin access required" in resp.data

    resp = client.get("/admin/codes/expired", follow_redirects=True)
    assert b"Admin access required" in resp.data


# -----------------------------------------------------------------------
# Fix 27: "Last edit by" always shown even when history is disabled
# -----------------------------------------------------------------------
def test_editor_info_shown_with_history_disabled(logged_in_admin):
    import db
    import config
    assert config.PAGE_HISTORY_ENABLED is False
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated content", 1, "test edit")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"Last edit by" in resp.data
    assert b"View history" not in resp.data
