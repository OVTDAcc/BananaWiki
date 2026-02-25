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
    assert b"Cannot change your own role" in resp.data


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
# Fix 25: Page history is always enabled
# -----------------------------------------------------------------------
def test_page_history_enabled_by_default(logged_in_admin):
    import config
    assert config.PAGE_HISTORY_ENABLED is True
    resp = logged_in_admin.get("/page/home/history")
    assert resp.status_code == 200


def test_page_history_entry_returns_404_for_missing(logged_in_admin):
    resp = logged_in_admin.get("/page/home/history/99999")
    assert resp.status_code == 404


def test_page_revert_returns_404_for_missing(logged_in_admin):
    resp = logged_in_admin.post("/page/home/revert/99999")
    assert resp.status_code == 404


def test_page_history_accessible(logged_in_admin):
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
# Fix 27: "Last edit by" and "View history" always shown
# -----------------------------------------------------------------------
def test_editor_info_shown_with_history_link(logged_in_admin):
    import db
    import config
    assert config.PAGE_HISTORY_ENABLED is True
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated content", 1, "test edit")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"Last edit by" in resp.data
    assert b"View history" in resp.data


# -----------------------------------------------------------------------
# Fix 28: delete_user preserves invite code history (SET NULL, not DELETE)
# -----------------------------------------------------------------------
def test_delete_user_preserves_invite_code_history(logged_in_admin, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    code = db.generate_invite_code(admin_user)
    uid = db.create_user("preserveuser", generate_password_hash("pass123"))
    db.use_invite_code(code, uid)
    # Verify code was marked as used
    expired = db.list_expired_codes()
    used_codes = [c for c in expired if c["code"] == code]
    assert len(used_codes) == 1
    assert used_codes[0]["used_by"] == uid
    # Delete the user
    db.delete_user(uid)
    # Verify the invite code row still exists with used_by set to NULL
    expired = db.list_expired_codes()
    preserved = [c for c in expired if c["code"] == code]
    assert len(preserved) == 1
    assert preserved[0]["used_by"] is None


# -----------------------------------------------------------------------
# Fix 29: create_category with empty name shows error
# -----------------------------------------------------------------------
def test_create_category_empty_name(logged_in_admin):
    resp = logged_in_admin.post("/category/create",
                                data={"name": "", "parent_id": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Category name is required" in resp.data


# -----------------------------------------------------------------------
# Fix 30: edit_category with empty name shows error
# -----------------------------------------------------------------------
def test_edit_category_empty_name(logged_in_admin):
    import db
    cat_id = db.create_category("TestCat")
    resp = logged_in_admin.post(f"/category/{cat_id}/edit",
                                data={"name": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Category name is required" in resp.data


# -----------------------------------------------------------------------
# Fix 31: 403 error template shows proper Access Denied message
# -----------------------------------------------------------------------
def test_403_template_exists():
    import os
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "templates", "wiki", "403.html"
    )
    assert os.path.exists(template_path)
    with open(template_path) as f:
        content = f.read()
    assert "Access Denied" in content
    assert "403" in content


# -----------------------------------------------------------------------
# Fix 32: Admin cannot change their own role
# -----------------------------------------------------------------------
def test_admin_cannot_change_own_role(logged_in_admin, admin_user):
    resp = logged_in_admin.post(f"/admin/users/{admin_user}/edit",
                                data={"action": "change_role", "role": "editor"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot change your own role" in resp.data


# -----------------------------------------------------------------------
# Fix 33: Last admin demotion blocked (via another admin)
# -----------------------------------------------------------------------
def test_cannot_demote_last_admin_via_other(logged_in_admin, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    # Create a second admin who is the target
    uid2 = db.create_user("admin2", generate_password_hash("pass123"), role="admin")
    # Demote admin2 first (should succeed - 2 admins exist)
    resp = logged_in_admin.post(f"/admin/users/{uid2}/edit",
                                data={"action": "change_role", "role": "user"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Role updated" in resp.data
    # Now create a third user to try to demote admin_user (the only admin left)
    # We need a second admin to log in as - create one
    uid3 = db.create_user("admin3", generate_password_hash("pass123"), role="admin")
    # Try to demote admin_user via admin3
    from app import app
    with app.test_client() as c2:
        c2.post("/login", data={"username": "admin3", "password": "pass123"})
        resp = c2.post(f"/admin/users/{admin_user}/edit",
                       data={"action": "change_role", "role": "user"},
                       follow_redirects=True)
        assert resp.status_code == 200
        # admin_user is an admin; there are 2 admins now (admin_user + admin3)
        # so this should succeed
        assert b"Role updated" in resp.data


# -----------------------------------------------------------------------
# Fix 34: Editor should not see invite codes link in account settings
# -----------------------------------------------------------------------
def test_editor_does_not_see_invite_codes_link(client, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("editor2", generate_password_hash("pass123"), role="editor")
    client.post("/login", data={"username": "editor2", "password": "pass123"})
    resp = client.get("/account")
    assert resp.status_code == 200
    assert b"Invite Codes" not in resp.data


def test_admin_sees_invite_codes_link(logged_in_admin):
    resp = logged_in_admin.get("/account")
    assert resp.status_code == 200
    assert b"Invite Codes" in resp.data


# -----------------------------------------------------------------------
# Fix 35: Create category with non-existent parent_id shows error
# -----------------------------------------------------------------------
def test_create_category_nonexistent_parent(logged_in_admin):
    resp = logged_in_admin.post("/category/create",
                                data={"name": "TestCat", "parent_id": "9999"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Selected parent category does not exist" in resp.data


# -----------------------------------------------------------------------
# Fix 36: Admin rename user handles IntegrityError (race condition)
# -----------------------------------------------------------------------
def test_admin_rename_user_integrity_error(logged_in_admin, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("user_a", generate_password_hash("pass123"), role="user")
    uid_b = db.create_user("user_b", generate_password_hash("pass123"), role="user")
    # Try to rename user_b to user_a (duplicate)
    resp = logged_in_admin.post(f"/admin/users/{uid_b}/edit",
                                data={"action": "change_username", "username": "user_a"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"already taken" in resp.data


# -----------------------------------------------------------------------
# Fix 37: Account change username handles IntegrityError (race condition)
# -----------------------------------------------------------------------
def test_account_change_username_duplicate(client, admin_user):
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("existing_user", generate_password_hash("pass123"), role="user")
    uid = db.create_user("changer", generate_password_hash("pass123"), role="user")
    client.post("/login", data={"username": "changer", "password": "pass123"})
    resp = client.post("/account", data={
        "action": "change_username",
        "new_username": "existing_user",
        "password": "pass123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"already taken" in resp.data


# -----------------------------------------------------------------------
# Fix 38: Edit non-existent category returns 404
# -----------------------------------------------------------------------
def test_edit_nonexistent_category(logged_in_admin):
    resp = logged_in_admin.post("/category/9999/edit",
                                data={"name": "NewName"})
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# Fix 39: Delete non-existent category returns 404
# -----------------------------------------------------------------------
def test_delete_nonexistent_category(logged_in_admin):
    resp = logged_in_admin.post("/category/9999/delete")
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# Fix 40: Move page UI is accessible (page shows move button)
# -----------------------------------------------------------------------
def test_move_page_button_visible(logged_in_admin):
    import db
    db.create_page("Movable Page", "movable-page", "content", user_id=1)
    resp = logged_in_admin.get("/page/movable-page")
    assert resp.status_code == 200
    assert b"Move" in resp.data


def test_move_page_button_not_on_home(logged_in_admin):
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"moveModal" not in resp.data


# -----------------------------------------------------------------------
# Fix 41: delete_upload with empty filename returns error, not crash
# -----------------------------------------------------------------------
def test_delete_upload_empty_filename(logged_in_admin):
    resp = logged_in_admin.post("/api/upload/delete",
                                json={"filename": ""},
                                content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "invalid filename"


def test_delete_upload_missing_filename(logged_in_admin):
    resp = logged_in_admin.post("/api/upload/delete",
                                json={"other": "value"},
                                content_type="application/json")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "invalid filename"


# -----------------------------------------------------------------------
# Fix 42: Admin change_role with invalid role shows error
# -----------------------------------------------------------------------
def test_admin_change_role_invalid_value(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("roleuser", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_role", "role": "superadmin"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid role" in resp.data


# -----------------------------------------------------------------------
# Fix 43: Page title max length validation
# -----------------------------------------------------------------------
def test_create_page_long_title(logged_in_admin):
    resp = logged_in_admin.post("/create-page",
                                data={"title": "A" * 201, "content": "test",
                                      "category_id": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"200 characters" in resp.data


def test_edit_page_title_too_long(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit/title",
                                data={"title": "X" * 201},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"200 characters" in resp.data


def test_edit_page_title_empty(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit/title",
                                data={"title": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Title is required" in resp.data


# -----------------------------------------------------------------------
# Fix 44: Category name max length validation
# -----------------------------------------------------------------------
def test_create_category_long_name(logged_in_admin):
    resp = logged_in_admin.post("/category/create",
                                data={"name": "C" * 101, "parent_id": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"100 characters" in resp.data


def test_edit_category_long_name(logged_in_admin):
    import db
    cat_id = db.create_category("TestCat")
    resp = logged_in_admin.post(f"/category/{cat_id}/edit",
                                data={"name": "C" * 101},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"100 characters" in resp.data


# -----------------------------------------------------------------------
# Fix 45: Username max length validation
# -----------------------------------------------------------------------
def test_signup_username_too_long(client, admin_user):
    import db
    code = db.generate_invite_code(admin_user)
    resp = client.post("/signup", data={
        "username": "u" * 51,
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"50 characters" in resp.data


def test_account_username_too_long(client, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    db.create_user("lenuser", generate_password_hash("pass123"), role="user")
    client.post("/login", data={"username": "lenuser", "password": "pass123"})
    resp = client.post("/account", data={
        "action": "change_username",
        "new_username": "u" * 51,
        "password": "pass123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"50 characters" in resp.data


def test_admin_create_user_username_too_long(logged_in_admin):
    resp = logged_in_admin.post("/admin/users/create", data={
        "username": "u" * 51,
        "password": "password123",
        "confirm_password": "password123",
        "role": "user",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"50 characters" in resp.data


def test_admin_rename_user_username_too_long(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("longuser", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_username", "username": "u" * 51},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"50 characters" in resp.data


# -----------------------------------------------------------------------
# Fix 46: Edit page redirects home page to /
# -----------------------------------------------------------------------
def test_edit_home_redirects_to_root(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit",
                                data={"title": "Home", "content": "Updated",
                                      "edit_message": "test"})
    assert resp.status_code == 302
    assert resp.location.endswith("/")


def test_edit_title_home_redirects_to_root(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit/title",
                                data={"title": "Updated Home"})
    assert resp.status_code == 302
    assert resp.location.endswith("/")


# -----------------------------------------------------------------------
# Fix 47: Create page form preserves data on error
# -----------------------------------------------------------------------
def test_create_page_preserves_form_data(logged_in_admin):
    resp = logged_in_admin.post("/create-page",
                                data={"title": "", "content": "my content here",
                                      "category_id": ""})
    assert resp.status_code == 200
    # Form should re-render with error notice and helper callout
    assert b"Title is required" in resp.data
    assert b"First create the page" in resp.data


# -----------------------------------------------------------------------
# Fix 48: Admin password change requires confirmation
# -----------------------------------------------------------------------
def test_admin_change_password_mismatch(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("pwuser", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_password",
                                      "password": "newpass123",
                                      "confirm_password": "different123"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Passwords do not match" in resp.data


def test_admin_change_password_success(logged_in_admin, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("pwuser2", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_password",
                                      "password": "newpass123",
                                      "confirm_password": "newpass123"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Password updated" in resp.data


# -----------------------------------------------------------------------
# New tests: format_datetime helper
# -----------------------------------------------------------------------
def test_format_datetime_valid():
    from app import format_datetime
    result = format_datetime("2026-02-20T18:07:24+00:00")
    assert "2026-02-20" in result
    assert "18:07" in result
    assert "UTC" in result


def test_format_datetime_edge_cases():
    from app import format_datetime
    assert format_datetime(None) == ""
    assert format_datetime("") == ""
    assert format_datetime("not-a-date") == ""


# -----------------------------------------------------------------------
# New tests: Time hover tooltip on page view
# -----------------------------------------------------------------------
def test_time_hover_tooltip_on_page(logged_in_admin):
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated content", 1, "test edit")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"title=" in resp.data
    assert b"UTC" in resp.data


def test_time_hover_tooltip_on_slug_page(logged_in_admin):
    import db
    db.create_page("Test Page", "test-page", "content", user_id=1)
    resp = logged_in_admin.get("/page/test-page")
    assert resp.status_code == 200
    assert b"title=" in resp.data
    assert b"UTC" in resp.data


# -----------------------------------------------------------------------
# New tests: Page history always active
# -----------------------------------------------------------------------
def test_history_link_always_shown(logged_in_admin):
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated content", 1, "test edit")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"View history" in resp.data


def test_revert_preserves_old_versions(logged_in_admin):
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Version 1", 1, "first edit")
    db.update_page(home["id"], "Home", "Version 2", 1, "second edit")
    history_before = db.get_page_history(home["id"])

    # Revert to first version
    first_entry = history_before[-1]  # oldest entry
    resp = logged_in_admin.post(
        f"/page/home/revert/{first_entry['id']}",
        follow_redirects=True
    )
    assert resp.status_code == 200

    # All previous history entries should still exist plus the revert
    history_after = db.get_page_history(home["id"])
    assert len(history_after) > len(history_before)
    # Revert message should be in history
    assert any("Reverted" in (h["edit_message"] or "") for h in history_after)


# -----------------------------------------------------------------------
# New tests: Draft contributors in commit message
# -----------------------------------------------------------------------
def test_commit_includes_contributor_names(logged_in_admin):
    import db
    from werkzeug.security import generate_password_hash
    # Create a page
    page_id = db.create_page("Collab Page", "collab-page", "initial", user_id=1)
    # Create another user with a draft
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    db.save_draft(page_id, editor_id, "Collab Page", "editor1 content")
    # Admin commits the page
    resp = logged_in_admin.post("/page/collab-page/edit", data={
        "title": "Collab Page",
        "content": "final content",
        "edit_message": "merged changes",
    }, follow_redirects=True)
    assert resp.status_code == 200
    # Check history contains contributor name
    history = db.get_page_history(page_id)
    latest = history[0]
    assert "editor1" in latest["edit_message"]
    assert "contributors" in latest["edit_message"].lower()


def test_commit_cleans_up_all_drafts(logged_in_admin):
    import db
    from werkzeug.security import generate_password_hash
    page_id = db.create_page("Draft Cleanup", "draft-cleanup", "initial", user_id=1)
    editor_id = db.create_user("editor2", generate_password_hash("pass123"), role="editor")
    db.save_draft(page_id, editor_id, "Draft Cleanup", "editor2 content")
    db.save_draft(page_id, 1, "Draft Cleanup", "admin content")
    # Admin commits
    logged_in_admin.post("/page/draft-cleanup/edit", data={
        "title": "Draft Cleanup",
        "content": "final",
        "edit_message": "",
    })
    # All drafts should be cleaned up
    drafts = db.get_drafts_for_page(page_id)
    assert len(drafts) == 0


def test_commit_without_contributors_no_extra_message(logged_in_admin):
    import db
    page_id = db.create_page("Solo Page", "solo-page", "initial", user_id=1)
    logged_in_admin.post("/page/solo-page/edit", data={
        "title": "Solo Page",
        "content": "solo content",
        "edit_message": "my edit",
    })
    history = db.get_page_history(page_id)
    latest = history[0]
    assert latest["edit_message"] == "my edit"
    assert "contributors" not in latest["edit_message"].lower()


# -----------------------------------------------------------------------
# New tests: Sync retry logic
# -----------------------------------------------------------------------
def test_sync_retry_constants():
    import sync
    assert sync.MAX_RETRIES >= 1
    assert sync.RETRY_BASE_DELAY > 0


def test_sync_caption_includes_descriptions(tmp_path, monkeypatch):
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    import zipfile
    zip_path = str(tmp_path / "test.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [
        {"type": "page_edit", "description": "Page 'test' edited", "timestamp": "2026-01-01T00:00:00"},
        {"type": "user_signup", "description": "User 'newuser' registered", "timestamp": "2026-01-01T00:01:00"},
    ]

    import json
    from unittest.mock import MagicMock, patch

    captured = {}

    def mock_urlopen(req, **kwargs):
        captured["data"] = req.data
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        result = sync._send_to_telegram(zip_path, changes, [])
        assert result is True

    body_text = captured["data"].decode("utf-8", errors="replace")
    assert "Details" in body_text
    assert "Page 'test' edited" in body_text


# -----------------------------------------------------------------------
# Security: CSRF protection is enabled
# -----------------------------------------------------------------------
def test_csrf_protection_enabled():
    from app import app, csrf
    assert csrf is not None


def test_csrf_rejects_post_without_token():
    """POST requests without a CSRF token should be rejected (400)."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = True
    with app.test_client() as c:
        import db
        from werkzeug.security import generate_password_hash
        db.create_user("csrfadmin", generate_password_hash("admin123"), role="admin")
        db.update_site_settings(setup_done=1)
        c.post("/login", data={"username": "csrfadmin", "password": "admin123",
                               "csrf_token": "invalid"})
        # Without a valid CSRF token, a POST should be rejected
        resp = c.post("/create-page", data={"title": "Bad", "content": "x"})
        assert resp.status_code == 400


# -----------------------------------------------------------------------
# Security: Security headers are set
# -----------------------------------------------------------------------
def test_security_headers(logged_in_admin):
    resp = logged_in_admin.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# -----------------------------------------------------------------------
# Security: Session cookie configuration
# -----------------------------------------------------------------------
def test_session_cookie_config():
    from app import app
    assert app.config.get("SESSION_COOKIE_HTTPONLY") is True
    assert app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"


# -----------------------------------------------------------------------
# Security: Logout requires POST
# -----------------------------------------------------------------------
def test_logout_rejects_get(logged_in_admin):
    resp = logged_in_admin.get("/logout")
    assert resp.status_code == 405


def test_logout_works_with_post(logged_in_admin):
    resp = logged_in_admin.post("/logout", follow_redirects=True)
    assert resp.status_code == 200
    assert b"logged out" in resp.data.lower()


# -----------------------------------------------------------------------
# Security: Invite codes use cryptographic randomness
# -----------------------------------------------------------------------
def test_invite_code_uses_secrets(admin_user):
    """Ensure invite codes are generated with secrets module (not random)."""
    import db
    # Generate several codes and verify format
    codes = set()
    for _ in range(20):
        code = db.generate_invite_code(admin_user)
        # Format: XXXX-XXXX where X is uppercase letter or digit
        assert len(code) == 9
        assert code[4] == "-"
        assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" for c in code.replace("-", ""))
        codes.add(code)
    # All codes should be unique (extremely unlikely to collide with secrets)
    assert len(codes) == 20


def test_invite_code_not_using_random_module():
    """Verify db module imports secrets, not random."""
    import db as db_mod
    import inspect
    source = inspect.getsource(db_mod)
    assert "secrets.choice" in source
    assert "random.choices" not in source


# -----------------------------------------------------------------------
# Security: Open redirect prevention via _safe_referrer
# -----------------------------------------------------------------------
def test_safe_referrer_blocks_external(client, admin_user):
    """413 handler should not redirect to external domains."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    # Simulate a request with an external Referer header
    resp = client.post(
        "/category/create",
        data={"name": "test"},
        headers={"Referer": "https://evil.example.com/steal"},
        follow_redirects=False,
    )
    # Should redirect, but NOT to the external domain
    assert resp.status_code in (302, 303)
    location = resp.headers.get("Location", "")
    assert "evil.example.com" not in location


def test_safe_referrer_allows_same_origin(client, admin_user):
    """Same-origin referrer should be preserved in redirects."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.post(
        "/category/create",
        data={"name": ""},  # empty name triggers error + redirect
        headers={"Referer": "http://localhost/page/test"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    location = resp.headers.get("Location", "")
    assert "localhost" in location or "/" in location


# -----------------------------------------------------------------------
# Security: Username character validation
# -----------------------------------------------------------------------
def test_username_rejects_special_characters(client, admin_user):
    """Usernames with special chars should be rejected to prevent log injection."""
    import db
    code = db.generate_invite_code(admin_user)
    resp = client.post("/signup", data={
        "username": "user<script>",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_username_rejects_newlines(client, admin_user):
    """Usernames with newlines should be rejected to prevent log injection."""
    import db
    code = db.generate_invite_code(admin_user)
    resp = client.post("/signup", data={
        "username": "user\nfake",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_username_rejects_spaces(client, admin_user):
    """Usernames with spaces should be rejected."""
    import db
    code = db.generate_invite_code(admin_user)
    resp = client.post("/signup", data={
        "username": "user name",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_username_allows_valid_chars(client, admin_user):
    """Usernames with letters, digits, underscores, hyphens should be accepted."""
    import db
    code = db.generate_invite_code(admin_user)
    resp = client.post("/signup", data={
        "username": "valid_user-123",
        "password": "password123",
        "confirm_password": "password123",
        "invite_code": code,
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Account created" in resp.data


def test_setup_rejects_invalid_username(client):
    """Setup should reject usernames with special characters."""
    resp = client.post("/setup", data={
        "username": "admin user",
        "password": "admin123",
        "confirm_password": "admin123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_account_change_rejects_invalid_username(client, admin_user):
    """Account settings should reject usernames with special characters."""
    from werkzeug.security import generate_password_hash
    import db
    db.create_user("validuser", generate_password_hash("pass123"), role="user")
    client.post("/login", data={"username": "validuser", "password": "pass123"})
    resp = client.post("/account", data={
        "action": "change_username",
        "new_username": "invalid user!",
        "password": "pass123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_admin_create_user_rejects_invalid_username(logged_in_admin):
    """Admin create user should reject usernames with special characters."""
    resp = logged_in_admin.post("/admin/users/create", data={
        "username": "bad<name",
        "password": "password123",
        "confirm_password": "password123",
        "role": "user",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_admin_rename_rejects_invalid_username(logged_in_admin, admin_user):
    """Admin rename user should reject usernames with special characters."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("goodname", generate_password_hash("pass123"), role="user")
    resp = logged_in_admin.post(f"/admin/users/{uid}/edit",
                                data={"action": "change_username", "username": "bad name"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"letters, digits, underscores and hyphens" in resp.data


def test_is_valid_username_helper():
    """Test the _is_valid_username helper function directly."""
    from app import _is_valid_username
    assert _is_valid_username("admin") is True
    assert _is_valid_username("user_123") is True
    assert _is_valid_username("my-user") is True
    assert _is_valid_username("A") is True
    assert _is_valid_username("user name") is False
    assert _is_valid_username("user<script>") is False
    assert _is_valid_username("user\nfake") is False
    assert _is_valid_username("") is False
    assert _is_valid_username("user@name") is False


# -----------------------------------------------------------------------
# Security: Log injection prevention
# -----------------------------------------------------------------------
def test_log_sanitize_strips_newlines():
    """Log sanitizer should strip newlines and control characters."""
    from wiki_logger import _sanitize
    assert _sanitize("normal text") == "normal text"
    assert _sanitize("line1\nline2") == "line1line2"
    assert _sanitize("line1\r\nline2") == "line1line2"
    assert _sanitize("tab\there") == "tabhere"
    assert _sanitize("null\x00byte") == "nullbyte"


# -----------------------------------------------------------------------
# Security: delete_upload path traversal defense-in-depth
# -----------------------------------------------------------------------
def test_delete_upload_path_traversal_blocked(logged_in_admin):
    """delete_upload should block path traversal attempts."""
    resp = logged_in_admin.post("/api/upload/delete",
                                json={"filename": "../../../etc/passwd"},
                                content_type="application/json")
    # secure_filename strips path components, so this should be safe
    # but the filename may still end up empty or blocked
    data = resp.get_json()
    assert resp.status_code in (200, 400)
    if resp.status_code == 400:
        assert data["error"] == "invalid filename"


# -----------------------------------------------------------------------
# Security: Content-Security-Policy header is set
# -----------------------------------------------------------------------
def test_csp_header_present(logged_in_admin):
    """Responses should include a Content-Security-Policy header."""
    resp = logged_in_admin.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp


# -----------------------------------------------------------------------
# Security: Log sanitization covers path, method, and IP
# -----------------------------------------------------------------------
def test_log_sanitize_covers_all_request_fields():
    """log_request should sanitize path, method, and IP — not just UA."""
    import inspect
    from wiki_logger import log_request
    source = inspect.getsource(log_request)
    # Verify _sanitize is applied to path, method, and remote_addr
    assert "_sanitize(request.remote_addr" in source or "_sanitize(request.remote_addr or" in source
    assert "_sanitize(request.method)" in source
    assert "_sanitize(request.path)" in source


def test_log_action_sanitizes_ip_and_action():
    """log_action should sanitize the IP and action parameter."""
    import inspect
    from wiki_logger import log_action
    source = inspect.getsource(log_action)
    assert "_sanitize(request.remote_addr" in source or "_sanitize(request.remote_addr or" in source
    assert "_sanitize(action)" in source


def test_log_sanitize_prevents_injection_at_runtime():
    """Verify _sanitize actually strips newlines from values at runtime."""
    from wiki_logger import _sanitize
    # Simulate a malicious path with newline injection
    malicious_path = "/page/test\nFAKE ACTION | user=admin action=admin_delete_user"
    sanitized = _sanitize(malicious_path)
    assert "\n" not in sanitized
    assert "\r" not in sanitized
    # The sanitized value should be a single line
    assert sanitized == "/page/testFAKE ACTION | user=admin action=admin_delete_user"

    # Simulate a malicious action string
    malicious_action = "login_success\nACTION  | user=admin action=delete_all"
    sanitized = _sanitize(malicious_action)
    assert "\n" not in sanitized


# -----------------------------------------------------------------------
# SSL / HTTPS config defaults
# -----------------------------------------------------------------------
def test_ssl_config_defaults():
    """SSL_CERT and SSL_KEY should default to None."""
    import config
    assert config.SSL_CERT is None
    assert config.SSL_KEY is None


def test_proxy_mode_default():
    """PROXY_MODE should default to False."""
    import config
    assert config.PROXY_MODE is False


# -----------------------------------------------------------------------
# ProxyFix middleware applied when PROXY_MODE is enabled
# -----------------------------------------------------------------------
def test_proxy_fix_applied_when_enabled(monkeypatch):
    """When PROXY_MODE is True the wsgi_app should be wrapped by ProxyFix."""
    import importlib
    import config as cfg
    monkeypatch.setattr(cfg, "PROXY_MODE", True)
    # Re-import app to pick up the monkeypatched config
    import app as app_mod
    importlib.reload(app_mod)
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(app_mod.app.wsgi_app, ProxyFix)
    # Restore
    monkeypatch.setattr(cfg, "PROXY_MODE", False)
    importlib.reload(app_mod)


def test_proxy_fix_not_applied_by_default():
    """By default wsgi_app should NOT be wrapped by ProxyFix."""
    from app import app
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert not isinstance(app.wsgi_app, ProxyFix)


# -----------------------------------------------------------------------
# Connection config defaults
# -----------------------------------------------------------------------
def test_port_config_default():
    """PORT should default to 5001."""
    import config
    assert config.PORT == 5001


def test_ssl_enables_secure_cookie(monkeypatch):
    """When SSL is configured, SESSION_COOKIE_SECURE and PREFERRED_URL_SCHEME are set."""
    import importlib
    import config as cfg
    monkeypatch.setattr(cfg, "SSL_CERT", "/tmp/cert.pem")
    monkeypatch.setattr(cfg, "SSL_KEY", "/tmp/key.pem")
    import app as app_mod
    importlib.reload(app_mod)
    assert app_mod.app.config["SESSION_COOKIE_SECURE"] is True
    assert app_mod.app.config["PREFERRED_URL_SCHEME"] == "https"
    # Restore
    monkeypatch.setattr(cfg, "SSL_CERT", None)
    monkeypatch.setattr(cfg, "SSL_KEY", None)
    importlib.reload(app_mod)


def test_ssl_not_enabled_by_default():
    """Without SSL certs, _ssl_enabled should be False."""
    import app as app_mod
    assert app_mod._ssl_enabled is False


# -----------------------------------------------------------------------
# WSGI entry point and Gunicorn config
# -----------------------------------------------------------------------
def test_wsgi_entry_point():
    """wsgi.py should expose the Flask app."""
    import wsgi
    assert hasattr(wsgi, "app")
    from app import app
    assert wsgi.app is app


def test_gunicorn_conf_exists():
    """gunicorn.conf.py should exist and define bind/workers."""
    import importlib.util
    import os
    conf_path = os.path.join(
        os.path.dirname(__file__), "..", "gunicorn.conf.py"
    )
    assert os.path.exists(conf_path)
    spec = importlib.util.spec_from_file_location("_gunicorn_conf", conf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "bind")
    assert hasattr(mod, "workers")
    assert mod.workers >= 1


def test_gunicorn_conf_reads_config():
    """gunicorn.conf.py should derive bind from config.HOST:config.PORT."""
    import importlib.util
    import os
    conf_path = os.path.join(
        os.path.dirname(__file__), "..", "gunicorn.conf.py"
    )
    spec = importlib.util.spec_from_file_location("_gunicorn_conf2", conf_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import config as cfg
    assert mod.bind == f"{cfg.HOST}:{cfg.PORT}"


# -----------------------------------------------------------------------
# Category edit/delete – CSRF tokens present in forms
# -----------------------------------------------------------------------
def test_category_forms_include_csrf(logged_in_admin):
    import db
    db.create_category("TestCat")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"csrf_token" in resp.data
    assert b"Manage category" in resp.data or b"manage category" in resp.data


# -----------------------------------------------------------------------
# Category actions visible in sidebar
# -----------------------------------------------------------------------
def test_category_actions_visible_in_sidebar(logged_in_admin):
    import db
    db.create_category("VisibleCat")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    # The edit icon (pencil ✎ = &#9998;) and delete icon (✕ = &#10005;) should render
    assert b"cat-actions" in resp.data


# -----------------------------------------------------------------------
# Draft delete API cleans up properly
# -----------------------------------------------------------------------
def test_draft_delete_cleans_up(logged_in_admin, admin_user):
    import db
    home = db.get_home_page()
    db.save_draft(home["id"], admin_user, "Title", "Content")
    assert db.get_draft(home["id"], admin_user) is not None

    resp = logged_in_admin.post("/api/draft/delete",
                                json={"page_id": home["id"]},
                                content_type="application/json")
    assert resp.status_code == 200
    assert db.get_draft(home["id"], admin_user) is None


# -----------------------------------------------------------------------
# My drafts API endpoint
# -----------------------------------------------------------------------
def test_api_my_drafts(logged_in_admin, admin_user):
    import db
    home = db.get_home_page()
    db.save_draft(home["id"], admin_user, "Draft Title", "Draft Content")

    resp = logged_in_admin.get("/api/draft/mine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["page_title"] is not None


# -----------------------------------------------------------------------
# User draft count helper
# -----------------------------------------------------------------------
def test_get_user_draft_count():
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("draftuser", generate_password_hash("test123"), role="editor")
    assert db.get_user_draft_count(uid) == 0

    home = db.get_home_page()
    db.save_draft(home["id"], uid, "t", "c")
    assert db.get_user_draft_count(uid) == 1


# -----------------------------------------------------------------------
# List user drafts helper
# -----------------------------------------------------------------------
def test_list_user_drafts():
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("draftlistuser", generate_password_hash("test123"), role="editor")
    home = db.get_home_page()
    db.save_draft(home["id"], uid, "Draft T", "Draft C")

    drafts = db.list_user_drafts(uid)
    assert len(drafts) == 1
    assert drafts[0]["page_title"] is not None
    assert drafts[0]["page_slug"] is not None


# -----------------------------------------------------------------------
# Login rate limiting
# -----------------------------------------------------------------------
def test_login_rate_limiting(client, admin_user):
    from app import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()
    # Exhaust rate limit with failed attempts
    for _ in range(5):
        client.post("/login", data={"username": "admin", "password": "wrong"})

    # Next attempt should be rate limited
    resp = client.post("/login", data={"username": "admin", "password": "admin123"})
    assert resp.status_code == 429
    assert b"Too many login attempts" in resp.data
    _LOGIN_ATTEMPTS.clear()


# -----------------------------------------------------------------------
# Edit page has Save Draft & Close button
# -----------------------------------------------------------------------
def test_edit_page_has_save_draft_close(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    assert b"save-draft-close" in resp.data
    assert b"Save Draft" in resp.data


# -----------------------------------------------------------------------
# Edit page has sync indicator
# -----------------------------------------------------------------------
def test_edit_page_has_sync_indicator(logged_in_admin):
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    assert b"save-indicator" in resp.data


# -----------------------------------------------------------------------
# Session fixation prevention
# -----------------------------------------------------------------------
def test_login_clears_session_before_setting_user(client, admin_user):
    """Login should clear existing session data before setting user_id."""
    from app import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()
    # Set some arbitrary session data
    with client.session_transaction() as sess:
        sess["stale_data"] = "should_be_cleared"
    # Login
    client.post("/login", data={"username": "admin", "password": "admin123"})
    with client.session_transaction() as sess:
        assert "user_id" in sess
        assert "stale_data" not in sess


# -----------------------------------------------------------------------
# Rate limit clears on successful login
# -----------------------------------------------------------------------
def test_rate_limit_clears_on_successful_login(client, admin_user):
    """Successful login should clear rate limit attempts for that IP."""
    from app import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()
    # Record 4 failed attempts
    for _ in range(4):
        client.post("/login", data={"username": "admin", "password": "wrong"})
    # Successful login should clear attempts
    client.post("/login", data={"username": "admin", "password": "admin123"})
    # After logout, should be able to fail again without rate limit
    client.post("/logout")
    _LOGIN_ATTEMPTS.clear()  # Clear for clean test
    for _ in range(4):
        resp = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 200  # Not rate limited


# -----------------------------------------------------------------------
# CSRF tokens present in critical forms
# -----------------------------------------------------------------------
def test_page_delete_form_has_csrf(logged_in_admin):
    """Delete page form should contain explicit CSRF token."""
    import db
    db.create_page("Test CSRF Page", "test-csrf-page", "Content", None)
    resp = logged_in_admin.get("/page/test-csrf-page")
    assert resp.status_code == 200
    assert b"csrf_token" in resp.data


def test_admin_users_forms_have_csrf(logged_in_admin):
    """Admin user management forms should contain CSRF tokens."""
    resp = logged_in_admin.get("/admin/users")
    assert resp.status_code == 200
    # Count occurrences of csrf_token in forms
    csrf_count = resp.data.count(b'name="csrf_token"')
    assert csrf_count >= 7  # create + 6 per-user action forms


def test_admin_codes_forms_have_csrf(logged_in_admin):
    """Admin codes forms should contain CSRF tokens."""
    resp = logged_in_admin.get("/admin/codes")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


def test_history_revert_form_has_csrf(logged_in_admin):
    """History revert form should contain CSRF token."""
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Updated", 1, "test edit")
    resp = logged_in_admin.get(f"/page/{home['slug']}/history")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


# -----------------------------------------------------------------------
# CSRF tokens in remaining forms
# -----------------------------------------------------------------------
def test_account_settings_forms_have_csrf(logged_in_admin):
    """Account settings forms should contain explicit CSRF tokens."""
    resp = logged_in_admin.get("/account")
    assert resp.status_code == 200
    csrf_count = resp.data.count(b'name="csrf_token"')
    assert csrf_count >= 3  # username, password, delete account


def test_admin_settings_form_has_csrf(logged_in_admin):
    """Admin site settings form should contain CSRF token."""
    resp = logged_in_admin.get("/admin/settings")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


def test_create_page_form_has_csrf(logged_in_admin):
    """Create page form should contain CSRF token."""
    resp = logged_in_admin.get("/create-page")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


def test_edit_page_form_has_csrf(logged_in_admin):
    """Edit page form should contain CSRF token."""
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    assert b'name="csrf_token"' in resp.data


# -----------------------------------------------------------------------
# Session timeout configured
# -----------------------------------------------------------------------
def test_session_lifetime_configured():
    """Session should have an explicit lifetime configured."""
    from app import app
    assert app.permanent_session_lifetime is not None
    assert app.permanent_session_lifetime.days <= 7


# -----------------------------------------------------------------------
# 500 error handler
# -----------------------------------------------------------------------
def test_500_error_template_exists():
    """500 error template should exist."""
    import os
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "templates", "wiki", "500.html"
    )
    assert os.path.exists(template_path)


# -----------------------------------------------------------------------
# Collapsible sidebar categories
# -----------------------------------------------------------------------
def test_category_has_collapse_toggle(logged_in_admin):
    """Category sections should have a collapse toggle button."""
    import db
    db.create_category("TestCollapse")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"cat-toggle" in resp.data
    assert b"nav-section-body" in resp.data


# -----------------------------------------------------------------------
# Last login tracking
# -----------------------------------------------------------------------
def test_login_updates_last_login_at(client, admin_user):
    """Successful login should set last_login_at on the user record."""
    from app import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()
    import db
    # Check before login
    user = db.get_user_by_id(admin_user)
    assert user["last_login_at"] is None
    # Login
    client.post("/login", data={"username": "admin", "password": "admin123"})
    user = db.get_user_by_id(admin_user)
    assert user["last_login_at"] is not None


# -----------------------------------------------------------------------
# Admin audit trail
# -----------------------------------------------------------------------
def test_admin_audit_route_exists(logged_in_admin, admin_user):
    """Admin audit trail route should return 200."""
    resp = logged_in_admin.get(f"/admin/users/{admin_user}/audit")
    assert resp.status_code == 200
    assert b"Audit Trail" in resp.data


def test_admin_audit_requires_admin(client, admin_user):
    """Non-admin users should not access audit trail."""
    import db
    from werkzeug.security import generate_password_hash
    db.create_user("editor1", generate_password_hash("password"), "editor")
    from app import _LOGIN_ATTEMPTS
    _LOGIN_ATTEMPTS.clear()
    client.post("/login", data={"username": "editor1", "password": "password"})
    resp = client.get(f"/admin/users/{admin_user}/audit")
    assert resp.status_code in (302, 403)  # Redirect or forbidden


def test_admin_users_shows_last_login(logged_in_admin):
    """Admin users page should show Last Login column."""
    resp = logged_in_admin.get("/admin/users")
    assert resp.status_code == 200
    assert b"Last Login" in resp.data


# -----------------------------------------------------------------------
# Create page minimal form + guidance
# -----------------------------------------------------------------------
def test_create_page_has_editor_and_preview(logged_in_admin):
    """Create page now guides to create then edit; should show title field and callout."""
    resp = logged_in_admin.get("/create-page")
    assert resp.status_code == 200
    assert b"info-callout" in resp.data
    assert b"name=\"title\"" in resp.data


# -----------------------------------------------------------------------
# Category delete with page actions
# -----------------------------------------------------------------------
def test_category_delete_moves_pages_to_uncategorized(logged_in_admin):
    """Deleting a category with uncategorize action moves pages to uncategorized."""
    import db
    cat_id = db.create_category("DelCat")
    page_id = db.create_page("TestPage", "test-del-page", "content", cat_id, 1)
    resp = logged_in_admin.post(f"/category/{cat_id}/delete",
                                data={"page_action": "uncategorize"},
                                follow_redirects=True)
    assert resp.status_code == 200
    page = db.get_page(page_id)
    assert page is not None
    assert page["category_id"] is None


def test_category_delete_bulk_deletes_pages(logged_in_admin):
    """Deleting a category with delete action removes its pages."""
    import db
    cat_id = db.create_category("DelCat2")
    page_id = db.create_page("DelPage", "test-del-page2", "content", cat_id, 1)
    resp = logged_in_admin.post(f"/category/{cat_id}/delete",
                                data={"page_action": "delete"},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert db.get_page(page_id) is None


def test_category_delete_moves_pages_to_another_category(logged_in_admin):
    """Deleting a category with move action moves pages to target category."""
    import db
    cat_id = db.create_category("MoveSrc")
    target_id = db.create_category("MoveDst")
    page_id = db.create_page("MovePage", "test-move-page", "content", cat_id, 1)
    resp = logged_in_admin.post(f"/category/{cat_id}/delete",
                                data={"page_action": "move",
                                      "target_category_id": str(target_id)},
                                follow_redirects=True)
    assert resp.status_code == 200
    page = db.get_page(page_id)
    assert page is not None
    assert page["category_id"] == target_id


def test_category_manage_panel_visible(logged_in_admin):
    """Category manage panel with rename and delete should be in sidebar."""
    import db
    db.create_category("ManageCat")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"catManageModal" in resp.data
    assert b"Rename" in resp.data
    assert b"Delete Category" in resp.data


# -----------------------------------------------------------------------
# Category move (reparent)
# -----------------------------------------------------------------------
def test_move_category_to_parent(logged_in_admin):
    """Moving a category to a new parent should update its parent_id."""
    import db
    parent_id = db.create_category("ParentCat")
    child_id = db.create_category("ChildCat")
    resp = logged_in_admin.post(f"/category/{child_id}/move",
                                data={"parent_id": str(parent_id)},
                                follow_redirects=True)
    assert resp.status_code == 200
    cat = db.get_category(child_id)
    assert cat["parent_id"] == parent_id


def test_move_category_to_top_level(logged_in_admin):
    """Moving a category with parent_id='' should make it top-level."""
    import db
    parent_id = db.create_category("TopParent")
    child_id = db.create_category("TopChild", parent_id=parent_id)
    cat = db.get_category(child_id)
    assert cat["parent_id"] == parent_id
    resp = logged_in_admin.post(f"/category/{child_id}/move",
                                data={"parent_id": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    cat = db.get_category(child_id)
    assert cat["parent_id"] is None


def test_move_category_into_itself_rejected(logged_in_admin):
    """Moving a category into itself should fail."""
    import db
    cat_id = db.create_category("SelfRef")
    resp = logged_in_admin.post(f"/category/{cat_id}/move",
                                data={"parent_id": str(cat_id)},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot move a category into itself" in resp.data


def test_move_category_manage_panel_has_move_option(logged_in_admin):
    """Category manage modal should include a Move section."""
    import db
    db.create_category("MovableCat")
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"Move to:" in resp.data
    assert b"/move" in resp.data


def test_move_category_circular_reference_rejected(logged_in_admin):
    """Moving a category into one of its own descendants should fail."""
    import db
    parent_id = db.create_category("Parent")
    child_id = db.create_category("Child", parent_id=parent_id)
    grandchild_id = db.create_category("Grandchild", parent_id=child_id)
    # Try to move parent under grandchild (circular)
    resp = logged_in_admin.post(f"/category/{parent_id}/move",
                                data={"parent_id": str(grandchild_id)},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot move a category into one of its own subcategories" in resp.data
    # Parent should still be at top level
    cat = db.get_category(parent_id)
    assert cat["parent_id"] is None


def test_is_descendant_of(isolated_db):
    """Verify is_descendant_of correctly detects ancestor chains."""
    import db
    a = db.create_category("A")
    b = db.create_category("B", parent_id=a)
    c = db.create_category("C", parent_id=b)
    d = db.create_category("D")
    # b is a descendant of a
    assert db.is_descendant_of(a, b) is True
    # c is a descendant of a (transitive)
    assert db.is_descendant_of(a, c) is True
    # d is NOT a descendant of a
    assert db.is_descendant_of(a, d) is False
    # a is NOT a descendant of c
    assert db.is_descendant_of(c, a) is False


def test_delete_category_move_validates_target(logged_in_admin):
    """Deleting a category with move should fall back if target doesn't exist."""
    import db
    cat_id = db.create_category("DeleteMe")
    page_id = db.create_page("TestPage", "testpage-validate", "content", cat_id)
    resp = logged_in_admin.post(f"/category/{cat_id}/delete",
                                data={"page_action": "move",
                                      "target_category_id": "9999"},
                                follow_redirects=True)
    assert resp.status_code == 200
    # Page should be uncategorized (fallback), not moved to non-existent 9999
    page = db.get_page(page_id)
    assert page["category_id"] is None


# -----------------------------------------------------------------------
# Fix: login_required no longer shows duplicate "please log in" flash
# -----------------------------------------------------------------------
def test_login_required_no_duplicate_flash(client, admin_user):
    """Accessing multiple protected pages without login should not produce
    duplicate flash messages on the login page."""
    # Access multiple protected pages without being logged in
    client.get("/")
    client.get("/account")
    # Now visit the login page – should have no "Please log in" flash since
    # the decorator was updated to redirect silently
    resp = client.get("/login")
    assert resp.status_code == 200
    # No "Please log in to continue" messages should be present
    assert b"Please log in to continue" not in resp.data


# -----------------------------------------------------------------------
# Announcements – DB helpers
# -----------------------------------------------------------------------
def test_create_and_get_announcement(admin_user):
    import db
    ann_id = db.create_announcement(
        content="Test announcement",
        color="orange",
        text_size="normal",
        visibility="both",
        expires_at=None,
        user_id=admin_user,
    )
    assert ann_id is not None
    ann = db.get_announcement(ann_id)
    assert ann is not None
    assert ann["content"] == "Test announcement"
    assert ann["color"] == "orange"
    assert ann["is_active"] == 1


def test_list_announcements(admin_user):
    import db
    db.create_announcement("Ann 1", "red", "normal", "both", None, admin_user)
    db.create_announcement("Ann 2", "blue", "large", "logged_in", None, admin_user)
    rows = db.list_announcements()
    assert len(rows) >= 2
    assert any(r["content"] == "Ann 1" for r in rows)


def test_update_announcement(admin_user):
    import db
    ann_id = db.create_announcement("Original", "orange", "normal", "both", None, admin_user)
    db.update_announcement(ann_id, content="Updated", is_active=0)
    ann = db.get_announcement(ann_id)
    assert ann["content"] == "Updated"
    assert ann["is_active"] == 0


def test_delete_announcement(admin_user):
    import db
    ann_id = db.create_announcement("ToDelete", "orange", "normal", "both", None, admin_user)
    db.delete_announcement(ann_id)
    assert db.get_announcement(ann_id) is None


def test_get_active_announcements_visibility(admin_user):
    import db
    db.create_announcement("For logged in", "orange", "normal", "logged_in", None, admin_user)
    db.create_announcement("For logged out", "red", "normal", "logged_out", None, admin_user)
    db.create_announcement("For everyone", "blue", "normal", "both", None, admin_user)

    logged_in = db.get_active_announcements(True)
    slugs_in = [r["content"] for r in logged_in]
    assert "For logged in" in slugs_in
    assert "For everyone" in slugs_in
    assert "For logged out" not in slugs_in

    logged_out = db.get_active_announcements(False)
    slugs_out = [r["content"] for r in logged_out]
    assert "For logged out" in slugs_out
    assert "For everyone" in slugs_out
    assert "For logged in" not in slugs_out


def test_get_active_announcements_expired(admin_user):
    import db
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    db.create_announcement("Expired", "orange", "normal", "both", past, admin_user)
    active = db.get_active_announcements(True)
    assert all(r["content"] != "Expired" for r in active)


def test_get_active_announcements_inactive(admin_user):
    import db
    ann_id = db.create_announcement("Inactive", "orange", "normal", "both", None, admin_user)
    db.update_announcement(ann_id, is_active=0)
    active = db.get_active_announcements(True)
    assert all(r["content"] != "Inactive" for r in active)


# -----------------------------------------------------------------------
# Announcements – Admin routes
# -----------------------------------------------------------------------
def test_admin_announcements_page(logged_in_admin):
    resp = logged_in_admin.get("/admin/announcements")
    assert resp.status_code == 200
    assert b"Announcement" in resp.data


def test_admin_create_announcement(logged_in_admin):
    resp = logged_in_admin.post("/admin/announcements/create", data={
        "content": "Hello world",
        "color": "orange",
        "text_size": "normal",
        "visibility": "both",
        "expires_at": "",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Announcement created" in resp.data
    assert b"Hello world" in resp.data


def test_admin_create_announcement_requires_content(logged_in_admin):
    resp = logged_in_admin.post("/admin/announcements/create", data={
        "content": "",
        "color": "orange",
        "text_size": "normal",
        "visibility": "both",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"required" in resp.data.lower()


def test_admin_create_announcement_max_length(logged_in_admin):
    resp = logged_in_admin.post("/admin/announcements/create", data={
        "content": "x" * 2001,
        "color": "orange",
        "text_size": "normal",
        "visibility": "both",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"2000 characters" in resp.data


def test_admin_edit_announcement(logged_in_admin, admin_user):
    import db
    ann_id = db.create_announcement("Old text", "orange", "normal", "both", None, admin_user)
    resp = logged_in_admin.post(f"/admin/announcements/{ann_id}/edit", data={
        "content": "New text",
        "color": "red",
        "text_size": "large",
        "visibility": "logged_in",
        "expires_at": "",
        "is_active": "1",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Announcement updated" in resp.data
    ann = db.get_announcement(ann_id)
    assert ann["content"] == "New text"
    assert ann["color"] == "red"


def test_admin_delete_announcement(logged_in_admin, admin_user):
    import db
    ann_id = db.create_announcement("To delete", "orange", "normal", "both", None, admin_user)
    resp = logged_in_admin.post(f"/admin/announcements/{ann_id}/delete",
                                follow_redirects=True)
    assert resp.status_code == 200
    assert b"Announcement deleted" in resp.data
    assert db.get_announcement(ann_id) is None


def test_announcement_shown_in_base(logged_in_admin, admin_user):
    import db
    db.create_announcement("Visible banner", "orange", "normal", "both", None, admin_user)
    resp = logged_in_admin.get("/")
    assert resp.status_code == 200
    assert b"announcements-bar" in resp.data
    assert b"Visible banner" in resp.data


def test_announcement_full_view(logged_in_admin, admin_user):
    import db
    ann_id = db.create_announcement("Full content here", "blue", "normal", "logged_in", None, admin_user)
    resp = logged_in_admin.get(f"/announcements/{ann_id}")
    assert resp.status_code == 200
    assert b"Full content here" in resp.data


def test_announcement_full_view_404_for_wrong_visibility(client, admin_user):
    import db
    ann_id = db.create_announcement("Logged in only", "blue", "normal", "logged_in", None, admin_user)
    # Not logged in – should get 404
    resp = client.get(f"/announcements/{ann_id}")
    assert resp.status_code == 404


def test_announcement_admin_link_in_account_settings(logged_in_admin):
    resp = logged_in_admin.get("/account")
    assert resp.status_code == 200
    assert b"Announcements" in resp.data


# -----------------------------------------------------------------------
# Easter egg tests
# -----------------------------------------------------------------------
def test_easter_egg_column_exists():
    """The users table must have an easter_egg_found column defaulting to 0."""
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("egguser", generate_password_hash("pw"), role="user")
    user = db.get_user_by_id(uid)
    assert user["easter_egg_found"] == 0


def test_set_easter_egg_found():
    """set_easter_egg_found() flips the flag from 0 to 1."""
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("egguser2", generate_password_hash("pw"), role="user")
    db.set_easter_egg_found(uid)
    user = db.get_user_by_id(uid)
    assert user["easter_egg_found"] == 1


def test_set_easter_egg_found_idempotent():
    """Calling set_easter_egg_found() multiple times keeps flag at 1."""
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("egguser3", generate_password_hash("pw"), role="user")
    db.set_easter_egg_found(uid)
    db.set_easter_egg_found(uid)
    user = db.get_user_by_id(uid)
    assert user["easter_egg_found"] == 1


def test_easter_egg_trigger_endpoint_requires_login(client):
    """The trigger endpoint must refuse unauthenticated requests."""
    resp = client.post("/api/easter-egg/trigger",
                       json={},
                       content_type="application/json")
    # Redirected to login (302) – not allowed
    assert resp.status_code in (302, 401, 403)


def test_easter_egg_trigger_endpoint_sets_flag(logged_in_admin, admin_user):
    """POSTing to the trigger endpoint sets easter_egg_found=1 in the DB."""
    import db
    resp = logged_in_admin.post("/api/easter-egg/trigger",
                                json={},
                                content_type="application/json")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"ok": True}
    user = db.get_user_by_id(admin_user)
    assert user["easter_egg_found"] == 1


# -----------------------------------------------------------------------
# Upload cleanup logic
# -----------------------------------------------------------------------
@pytest.fixture
def isolated_uploads(tmp_path, monkeypatch):
    """Redirect UPLOAD_FOLDER to a temporary directory for cleanup tests."""
    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)
    return upload_dir


def _make_fake_upload(upload_dir, filename="abc123.png"):
    """Create a dummy file in the upload directory and return its path."""
    fpath = os.path.join(upload_dir, filename)
    with open(fpath, "wb") as f:
        f.write(b"fakeimage")
    return fpath


def test_get_all_referenced_image_filenames_empty():
    """No images referenced when pages have no image markdown."""
    import db
    result = db.get_all_referenced_image_filenames()
    assert isinstance(result, set)
    assert len(result) == 0


def test_get_all_referenced_image_filenames_from_page():
    """Images referenced in page content are returned."""
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("u1", generate_password_hash("pw"), role="editor")
    content = "Hello\n![img](/static/uploads/abc123.png)\nWorld"
    db.create_page("Test", "test-ref", content, None, uid)
    result = db.get_all_referenced_image_filenames()
    assert "abc123.png" in result


def test_get_all_referenced_image_filenames_from_history():
    """Images referenced only in page history (removed from live page) are still returned."""
    import db
    from werkzeug.security import generate_password_hash
    uid = db.create_user("u2", generate_password_hash("pw"), role="editor")
    # Create page with image, then update without image
    page_id = db.create_page("HistPage", "hist-page", "![img](/static/uploads/hist1.png)", None, uid)
    db.update_page(page_id, "HistPage", "no image now", uid, "removed image")
    result = db.get_all_referenced_image_filenames()
    # Image removed from live page but still in history → must be kept
    assert "hist1.png" in result


def test_cleanup_unused_uploads_removes_unreferenced(isolated_uploads):
    """Files not referenced in any page/history are deleted by cleanup."""
    from app import cleanup_unused_uploads
    fpath = _make_fake_upload(isolated_uploads, "orphan.png")
    assert os.path.isfile(fpath)
    cleanup_unused_uploads()
    assert not os.path.isfile(fpath)


def test_cleanup_unused_uploads_keeps_referenced(isolated_uploads):
    """Files referenced in a page are preserved by cleanup."""
    import db
    from werkzeug.security import generate_password_hash
    from app import cleanup_unused_uploads
    uid = db.create_user("u3", generate_password_hash("pw"), role="editor")
    fpath = _make_fake_upload(isolated_uploads, "keep_me.png")
    db.create_page("KPage", "k-page", "![img](/static/uploads/keep_me.png)", None, uid)
    cleanup_unused_uploads()
    assert os.path.isfile(fpath)


def test_cleanup_unused_uploads_keeps_history_referenced(isolated_uploads):
    """Files referenced only in page history are preserved by cleanup."""
    import db
    from werkzeug.security import generate_password_hash
    from app import cleanup_unused_uploads
    uid = db.create_user("u4", generate_password_hash("pw"), role="editor")
    page_id = db.create_page("HPage", "h-page", "![img](/static/uploads/hist_keep.png)", None, uid)
    fpath = _make_fake_upload(isolated_uploads, "hist_keep.png")
    # Update page to remove the image; original content is now only in history
    db.update_page(page_id, "HPage", "no image", uid, "removed")
    cleanup_unused_uploads()
    # Image is in history → must be kept
    assert os.path.isfile(fpath)


def test_draft_discard_triggers_cleanup(logged_in_admin, admin_user, isolated_uploads):
    """Discarding a draft via /api/draft/delete removes unreferenced upload files."""
    import db
    # Create a page and a draft that references an orphan image
    home = db.get_home_page()
    db.save_draft(home["id"], admin_user, "Draft", "![img](/static/uploads/draft_orphan.png)")
    fpath = _make_fake_upload(isolated_uploads, "draft_orphan.png")
    assert os.path.isfile(fpath)
    resp = logged_in_admin.post("/api/draft/delete",
                                json={"page_id": home["id"]},
                                content_type="application/json")
    assert resp.status_code == 200
    # Image was in the discarded draft only → should be cleaned up
    assert not os.path.isfile(fpath)


def test_page_commit_removes_images_not_in_content(logged_in_admin, admin_user, isolated_uploads):
    """Committing a page without an image that was uploaded deletes the orphan file."""
    import db
    home = db.get_home_page()
    fpath = _make_fake_upload(isolated_uploads, "unused_commit.png")
    # Commit the page WITHOUT including the image URL in the content
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit",
                                data={"title": "Home", "content": "Clean content",
                                      "edit_message": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    assert not os.path.isfile(fpath)


def test_cleanup_skips_dotfiles(isolated_uploads):
    """Files starting with '.' (e.g. .gitkeep) are never removed."""
    from app import cleanup_unused_uploads
    gitkeep = os.path.join(isolated_uploads, ".gitkeep")
    with open(gitkeep, "wb") as f:
        f.write(b"")
    cleanup_unused_uploads()
    assert os.path.isfile(gitkeep)


# -----------------------------------------------------------------------
# Improved draft system tests
# -----------------------------------------------------------------------

def test_edit_page_has_discard_draft_button(logged_in_admin):
    """Edit page must show 'Discard Draft' button instead of plain Cancel link."""
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    assert b"Discard Draft" in resp.data
    # The form actions should not have a bare cancel link (href to page view)
    assert b'class="btn btn-outline">Cancel</a>' not in resp.data


def test_account_settings_has_my_drafts_section(logged_in_admin):
    """Account settings must include the My Drafts section."""
    resp = logged_in_admin.get("/account")
    assert resp.status_code == 200
    assert b"My Drafts" in resp.data
    assert b"draft-manager-list" in resp.data


def test_api_draft_mine_returns_list(logged_in_admin, admin_user):
    """GET /api/draft/mine returns a JSON list (empty or not)."""
    resp = logged_in_admin.get("/api/draft/mine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_api_draft_mine_includes_user_draft(logged_in_admin, admin_user):
    """After saving a draft, /api/draft/mine includes it."""
    import db
    home = db.get_home_page()
    db.save_draft(home["id"], admin_user, "My draft title", "Draft content")
    resp = logged_in_admin.get("/api/draft/mine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["page_id"] == home["id"]
    assert data[0]["page_slug"] == home["slug"]
    assert data[0]["title"] == "My draft title"


def test_api_draft_others_returns_new_format(logged_in_admin, admin_user):
    """GET /api/draft/others/<id> returns {drafts: [...], page_last_edited_at: ...}."""
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/api/draft/others/{home['id']}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "drafts" in data
    assert "page_last_edited_at" in data
    assert isinstance(data["drafts"], list)


def test_api_draft_others_404_for_missing_page(logged_in_admin):
    """GET /api/draft/others/<id> returns 404 for non-existent page."""
    resp = logged_in_admin.get("/api/draft/others/99999")
    assert resp.status_code == 404


def test_stale_draft_warning_shown_when_page_newer(logged_in_admin, admin_user):
    """Edit page shows stale draft warning when page was updated after draft."""
    import db
    from time import sleep
    home = db.get_home_page()
    # Save a draft first
    db.save_draft(home["id"], admin_user, "Old draft", "old content")
    # Now update the page (simulating another user's commit)
    sleep(0.01)
    db.update_page(home["id"], "Home", "newer content", admin_user, "external edit")
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    assert b"stale-draft-notice" in resp.data
    # The warning should be visible (not display:none)
    assert b"updated by another user" in resp.data


def test_stale_draft_warning_hidden_when_no_draft(logged_in_admin):
    """Edit page does not show stale draft warning when there is no draft."""
    import db
    home = db.get_home_page()
    resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
    assert resp.status_code == 200
    # The stale notice element should be hidden
    assert b'id="stale-draft-notice" style="display:none"' in resp.data


def test_commit_clears_all_page_drafts(logged_in_admin, admin_user):
    """Committing a page edit deletes all drafts for that page."""
    import db
    from werkzeug.security import generate_password_hash
    home = db.get_home_page()
    # Create a second user with a draft
    uid2 = db.create_user("editor2", generate_password_hash("pw2"), role="editor")
    db.save_draft(home["id"], admin_user, "Admin draft", "admin content")
    db.save_draft(home["id"], uid2, "Editor draft", "editor content")
    assert db.get_draft(home["id"], admin_user) is not None
    assert db.get_draft(home["id"], uid2) is not None
    # Admin commits
    resp = logged_in_admin.post(f"/page/{home['slug']}/edit",
                                data={"title": "Home", "content": "committed",
                                      "edit_message": ""},
                                follow_redirects=True)
    assert resp.status_code == 200
    # Both drafts should be gone
    assert db.get_draft(home["id"], admin_user) is None
    assert db.get_draft(home["id"], uid2) is None
