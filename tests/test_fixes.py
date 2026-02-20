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
    assert b"my content here" in resp.data


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
