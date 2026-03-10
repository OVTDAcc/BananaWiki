"""
Tests for the Page Reservation & Editing Lock System.

Tests reservation creation, expiry, cooldowns, race conditions,
permission guards, and integration with edit workflows.
"""
import os
import sys
import time
import pytest
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_LEVEL", "off")
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
def client():
    """Create a test client."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_user():
    """Create an admin user and mark setup as done."""
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1, page_reservations_enabled=1)
    return uid


@pytest.fixture
def editor_user():
    """Create an editor user."""
    import db
    db.update_site_settings(setup_done=1, page_reservations_enabled=1)
    uid = db.create_user("editor", generate_password_hash("editor123"), role="editor")
    return uid


@pytest.fixture
def editor2_user():
    """Create a second editor user."""
    import db
    uid = db.create_user("editor2", generate_password_hash("editor123"), role="editor")
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Return a client that is logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


@pytest.fixture
def logged_in_editor(client, editor_user):
    """Return a client that is logged in as editor."""
    client.post("/login", data={"username": "editor", "password": "editor123"})
    return client


@pytest.fixture
def test_page():
    """Create a test page."""
    import db
    db.update_site_settings(page_reservations_enabled=1)
    page_id = db.create_page("Test Page", "test-page", "Test content")
    return page_id


# ============================================================================
# UNIT TESTS: Database Functions
# ============================================================================

def test_reservations_disabled_by_default(isolated_db):
    """The reservation feature flag should default to off."""
    import db

    settings = db.get_site_settings()
    assert settings["page_reservations_enabled"] == 0

def test_reserve_page_success(editor_user, test_page):
    """Test successful page reservation."""
    import db

    reservation = db.reserve_page(test_page, editor_user)

    assert reservation is not None
    assert reservation["page_id"] == test_page
    assert reservation["user_id"] == editor_user
    assert reservation["reserved_at"] is not None
    assert reservation["expires_at"] is not None
    assert reservation["released_at"] is None

    # Check expiry is 48 hours in the future
    reserved_at = datetime.fromisoformat(reservation["reserved_at"]).replace(tzinfo=timezone.utc)
    expires_at = datetime.fromisoformat(reservation["expires_at"]).replace(tzinfo=timezone.utc)
    delta = expires_at - reserved_at
    assert delta.total_seconds() == config.PAGE_RESERVATION_DURATION_HOURS * 3600


def test_reserve_page_already_reserved(editor_user, editor2_user, test_page):
    """Test that reserving an already reserved page fails."""
    import db

    # Editor1 reserves the page
    db.reserve_page(test_page, editor_user)

    # Editor2 tries to reserve the same page
    with pytest.raises(ValueError, match="already reserved"):
        db.reserve_page(test_page, editor2_user)


def test_reserve_page_in_cooldown(editor_user, test_page):
    """Test that user cannot re-reserve during cooldown."""
    import db

    # Reserve and release
    db.reserve_page(test_page, editor_user)
    db.release_page_reservation(test_page, editor_user)

    # Try to reserve again immediately
    with pytest.raises(ValueError, match="cooldown"):
        db.reserve_page(test_page, editor_user)


def test_release_page_reservation(editor_user, test_page):
    """Test manual release of reservation."""
    import db

    # Reserve the page
    db.reserve_page(test_page, editor_user)

    # Release it
    released = db.release_page_reservation(test_page, editor_user)
    assert released is True

    # Verify page is no longer reserved
    status = db.get_page_reservation_status(test_page, editor_user)
    assert status["is_reserved"] is False


def test_release_creates_cooldown(editor_user, test_page):
    """Test that releasing a reservation creates a cooldown."""
    import db

    # Reserve and release
    db.reserve_page(test_page, editor_user)
    db.release_page_reservation(test_page, editor_user)

    # Check cooldown exists
    status = db.get_page_reservation_status(test_page, editor_user)
    assert status["user_in_cooldown"] is True
    assert status["cooldown_until"] is not None


def test_get_page_reservation_status_unreserved(test_page, editor_user):
    """Test status for unreserved page."""
    import db

    status = db.get_page_reservation_status(test_page, editor_user)

    assert status["is_reserved"] is False
    assert status["reserved_by"] is None
    assert status["reserved_by_username"] is None
    assert status["reserved_at"] is None
    assert status["expires_at"] is None
    assert status["time_remaining"] is None
    assert status["user_in_cooldown"] is False


def test_get_page_reservation_status_reserved(editor_user, test_page):
    """Test status for reserved page."""
    import db

    db.reserve_page(test_page, editor_user)
    status = db.get_page_reservation_status(test_page, editor_user)

    assert status["is_reserved"] is True
    assert status["reserved_by"] == editor_user
    assert status["reserved_by_username"] == "editor"
    assert status["reserved_at"] is not None
    assert status["expires_at"] is not None
    assert status["time_remaining"] is not None


def test_can_user_reserve_page(editor_user, test_page):
    """Test can_user_reserve_page function."""
    import db

    # Should be able to reserve initially
    can_reserve, reason = db.can_user_reserve_page(test_page, editor_user)
    assert can_reserve is True
    assert reason == ""

    # Reserve it
    db.reserve_page(test_page, editor_user)

    # Should not be able to reserve again
    can_reserve, reason = db.can_user_reserve_page(test_page, editor_user)
    assert can_reserve is False
    assert "already reserved" in reason.lower()


def test_can_user_edit_page_no_reservation(test_page, editor_user):
    """Test edit permission when page is not reserved."""
    import db

    can_edit, reason = db.can_user_edit_page(test_page, editor_user)
    assert can_edit is True
    assert reason == ""


def test_can_user_edit_page_own_reservation(test_page, editor_user):
    """Test edit permission when user holds the reservation."""
    import db

    db.reserve_page(test_page, editor_user)
    can_edit, reason = db.can_user_edit_page(test_page, editor_user)
    assert can_edit is True
    assert reason == ""


def test_can_user_edit_page_other_reservation(test_page, editor_user, editor2_user):
    """Test edit permission when another user holds the reservation."""
    import db

    db.reserve_page(test_page, editor_user)
    can_edit, reason = db.can_user_edit_page(test_page, editor2_user)
    assert can_edit is False
    assert "reserved by" in reason.lower()


def test_no_cross_page_cooldown(editor_user):
    """Test that cooldown only applies to the specific page."""
    import db

    page1 = db.create_page("Page 1", "page1", "Content 1")
    page2 = db.create_page("Page 2", "page2", "Content 2")

    # Reserve and release page1
    db.reserve_page(page1, editor_user)
    db.release_page_reservation(page1, editor_user)

    # User should still be able to reserve page2
    can_reserve, reason = db.can_user_reserve_page(page2, editor_user)
    assert can_reserve is True
    assert reason == ""

    # Verify can actually reserve page2
    reservation = db.reserve_page(page2, editor_user)
    assert reservation is not None


def test_cleanup_expired_reservations(editor_user, test_page, monkeypatch):
    """Test cleanup of expired reservations."""
    import db
    from datetime import datetime, timedelta, timezone

    # Create a reservation
    db.reserve_page(test_page, editor_user)

    # Get the reservation and manually set it to expired
    conn = db.get_db()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "UPDATE page_reservations SET expires_at=? WHERE page_id=?",
        (past, test_page)
    )
    conn.commit()
    conn.close()

    # Run cleanup
    result = db.cleanup_expired_reservations()
    assert result["reservations_cleaned"] == 1

    # Verify reservation is marked as released
    status = db.get_page_reservation_status(test_page, editor_user)
    assert status["is_reserved"] is False


def test_force_release_reservation(editor_user, test_page):
    """Test admin force release without cooldown."""
    import db

    # Reserve the page
    db.reserve_page(test_page, editor_user)

    # Force release (admin action)
    released = db.force_release_reservation(test_page)
    assert released is True

    # Verify page is no longer reserved
    status = db.get_page_reservation_status(test_page, editor_user)
    assert status["is_reserved"] is False

    # Verify NO cooldown was created (unlike regular release)
    assert status["user_in_cooldown"] is False


def test_get_user_reservations(editor_user):
    """Test getting all active reservations for a user."""
    import db

    page1 = db.create_page("Page 1", "page1", "Content 1")
    page2 = db.create_page("Page 2", "page2", "Content 2")
    page3 = db.create_page("Page 3", "page3", "Content 3")

    # Reserve pages 1 and 2
    db.reserve_page(page1, editor_user)
    db.reserve_page(page2, editor_user)

    # Get user's reservations
    reservations = db.get_user_reservations(editor_user)
    assert len(reservations) == 2

    # Verify page info is included
    page_ids = [r["page_id"] for r in reservations]
    assert page1 in page_ids
    assert page2 in page_ids
    assert page3 not in page_ids


# ============================================================================
# INTEGRATION TESTS: API Routes
# ============================================================================

def test_api_reserve_page(logged_in_editor, test_page):
    """Test POST /api/pages/<id>/reservation."""
    response = logged_in_editor.post(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert "reservation" in data


def test_api_reserve_page_already_reserved(logged_in_editor, logged_in_admin, test_page):
    """Test reserving an already reserved page returns 409."""
    # Editor reserves the page
    logged_in_editor.post(f"/api/pages/{test_page}/reservation")

    # Admin tries to reserve (different user)
    response = logged_in_admin.post(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 409
    data = response.get_json()
    assert "error" in data


def test_api_release_reservation(logged_in_editor, test_page):
    """Test DELETE /api/pages/<id>/reservation."""
    # Reserve first
    logged_in_editor.post(f"/api/pages/{test_page}/reservation")

    # Release
    response = logged_in_editor.delete(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True


def test_api_release_reservation_not_holding(logged_in_admin, test_page, editor_user):
    """Test releasing when not holding reservation returns 404."""
    import db

    # Editor reserves the page
    db.reserve_page(test_page, editor_user)

    # Admin tries to release (but doesn't hold it)
    response = logged_in_admin.delete(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 404


def test_api_get_reservation_status(logged_in_editor, test_page):
    """Test GET /api/pages/<id>/reservation/status."""
    response = logged_in_editor.get(f"/api/pages/{test_page}/reservation/status")
    assert response.status_code == 200
    data = response.get_json()
    assert "is_reserved" in data
    assert data["is_reserved"] is False


def test_api_get_reservation_status_reserved(logged_in_editor, test_page):
    """Test status endpoint returns correct info when reserved."""
    # Reserve the page
    logged_in_editor.post(f"/api/pages/{test_page}/reservation")

    # Get status
    response = logged_in_editor.get(f"/api/pages/{test_page}/reservation/status")
    data = response.get_json()
    assert data["is_reserved"] is True
    assert data["reserved_by"] is not None
    assert data["reserved_by_username"] == "editor"
    assert "time_remaining_text" in data


def test_api_reservation_requires_editor_role(client, test_page):
    """Test that reservation endpoints require editor role."""
    import db
    from werkzeug.security import generate_password_hash

    # Create regular user
    user_id = db.create_user("user", generate_password_hash("user123"), role="user")
    db.update_site_settings(setup_done=1)

    # Login as user
    client.post("/login", data={"username": "user", "password": "user123"})

    # Try to reserve
    response = client.post(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 302  # Redirect due to @editor_required


def test_api_reservation_returns_403_when_disabled(logged_in_editor, test_page):
    """Reservation API access is blocked when the feature is disabled."""
    import db

    db.update_site_settings(page_reservations_enabled=0)

    response = logged_in_editor.post(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 403
    assert b"currently disabled" in response.data


def test_admin_can_enable_page_reservations_from_settings(logged_in_admin):
    """Admins can toggle page reservations on from the settings screen."""
    import db

    response = logged_in_admin.post("/admin/settings", data={
        "site_name": "BananaWiki",
        "timezone": "UTC",
        "primary_color": "#7c8dc6",
        "secondary_color": "#151520",
        "accent_color": "#6e8aca",
        "text_color": "#b8bcc8",
        "sidebar_color": "#111118",
        "bg_color": "#0d0d14",
        "page_reservations_enabled": "1",
    })
    assert response.status_code in (200, 302)
    assert db.get_site_settings()["page_reservations_enabled"] == 1


def test_settings_page_has_page_reservations_checkbox(logged_in_admin):
    """The settings page exposes the reservation feature toggle."""
    response = logged_in_admin.get("/admin/settings")
    assert response.status_code == 200
    assert b"page_reservations_enabled" in response.data


# ============================================================================
# INTEGRATION TESTS: Edit Workflow
# ============================================================================

def test_edit_page_with_no_reservation(logged_in_editor, test_page):
    """Test editing a page with no active reservation."""
    response = logged_in_editor.get("/page/test-page/edit")
    assert response.status_code == 200


def test_edit_page_with_own_reservation(logged_in_editor, test_page):
    """Test editing a page user has reserved."""
    import db as db_mod

    # Reserve as the logged in user
    editor = db_mod.get_user_by_username("editor")
    db_mod.reserve_page(test_page, editor["id"])

    response = logged_in_editor.get("/page/test-page/edit")
    assert response.status_code == 200


def test_edit_page_reserved_by_other(logged_in_editor, test_page, editor2_user):
    """Test that editing is blocked when page is reserved by another user."""
    import db

    # Another user reserves the page
    db.reserve_page(test_page, editor2_user)

    # Try to edit
    response = logged_in_editor.get("/page/test-page/edit", follow_redirects=True)
    assert b"Cannot edit" in response.data or b"reserved by" in response.data.lower()


def test_edit_page_title_reserved_by_other_is_blocked(logged_in_editor, test_page, editor2_user):
    """Inline destructive edits are blocked for non-admins when reserved by another editor."""
    import db

    db.reserve_page(test_page, editor2_user)

    response = logged_in_editor.post(
        "/page/test-page/edit/title",
        data={"title": "Blocked Title"},
        follow_redirects=True,
    )
    assert b"currently reserved by" in response.data
    assert db.get_page(test_page)["title"] == "Test Page"


def test_move_page_is_still_allowed_when_reserved(logged_in_editor, test_page, editor2_user):
    """Moves remain available because they do not change page content."""
    import db

    destination = db.create_category("Moved")
    db.reserve_page(test_page, editor2_user)

    response = logged_in_editor.post(
        "/page/test-page/move",
        data={"category_id": str(destination)},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Page moved." in response.data
    assert db.get_page(test_page)["category_id"] == destination


def test_admin_reserved_edit_page_shows_override_warning(logged_in_admin, editor_user, test_page):
    """Admins are warned when they open a reserved page for editing."""
    import db

    db.reserve_page(test_page, editor_user)

    response = logged_in_admin.get("/page/test-page/edit")
    assert response.status_code == 200
    assert b"You are editing as an administrator" in response.data


def test_reservation_directory_lists_pages_and_actions(logged_in_editor, test_page):
    """Editors can discover reservable pages from the reservation directory."""
    response = logged_in_editor.get("/reservations")
    assert response.status_code == 200
    assert b"Page Reservations" in response.data
    assert b"Test Page" in response.data
    assert b"Reserve" in response.data


def test_reservation_directory_redirects_when_disabled(logged_in_editor, test_page):
    """The directory should redirect with guidance when reservations are disabled."""
    import db

    db.update_site_settings(page_reservations_enabled=0)

    response = logged_in_editor.get("/reservations", follow_redirects=True)
    assert response.status_code == 200
    assert b"currently disabled" in response.data


def test_reserved_page_is_editable_when_feature_disabled(logged_in_editor, test_page, editor2_user):
    """Disabling reservations should stop them from blocking edits."""
    import db

    db.reserve_page(test_page, editor2_user)
    db.update_site_settings(page_reservations_enabled=0)

    response = logged_in_editor.get("/page/test-page/edit")
    assert response.status_code == 200


def test_save_page_verifies_reservation(logged_in_editor, test_page, editor2_user):
    """Test that saving checks reservation status."""
    import db

    # Another user reserves the page
    db.reserve_page(test_page, editor2_user)

    # Try to save
    response = logged_in_editor.post(
        "/page/test-page/edit",
        data={"title": "Updated", "content": "Updated content"},
        follow_redirects=True
    )
    # Should be redirected with error
    assert b"Cannot save" in response.data or b"reserved" in response.data.lower()


def test_permission_guard_category_access(logged_in_editor, test_page):
    """Test that category permissions are checked for reservations."""
    import db
    from helpers._auth import editor_has_category_access

    # Create a category and set the page to that category
    cat_id = db.create_category("Restricted")
    db.update_page_category(test_page, cat_id)

    # Set editor to be restricted and not have access to this category
    editor = db.get_user_by_username("editor")
    conn = db.get_db()
    conn.execute(
        "INSERT INTO editor_category_access (user_id, restricted) VALUES (?, 1)",
        (editor["id"],)
    )
    conn.commit()
    conn.close()

    # Try to reserve - should fail due to category permissions
    response = logged_in_editor.post(f"/api/pages/{test_page}/reservation")
    assert response.status_code == 403


# ============================================================================
# RACE CONDITION TESTS
# ============================================================================

def test_concurrent_reservation_attempts(test_page):
    """Test that only one user can reserve when attempting simultaneously."""
    import db
    import threading
    from werkzeug.security import generate_password_hash

    # Create two users
    user1 = db.create_user("user1", generate_password_hash("pass"), role="editor")
    user2 = db.create_user("user2", generate_password_hash("pass"), role="editor")

    results = {"user1": None, "user2": None}

    def try_reserve(user_id, key):
        try:
            results[key] = db.reserve_page(test_page, user_id)
        except ValueError as e:
            results[key] = str(e)

    # Start two threads trying to reserve simultaneously
    t1 = threading.Thread(target=try_reserve, args=(user1, "user1"))
    t2 = threading.Thread(target=try_reserve, args=(user2, "user2"))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one should succeed, one should fail
    success_count = sum(1 for r in results.values() if isinstance(r, dict))
    error_count = sum(1 for r in results.values() if isinstance(r, str))

    assert success_count == 1
    assert error_count == 1


# ============================================================================
# EDGE CASE TESTS
# ============================================================================

def test_user_deleted_releases_reservation(test_page, editor_user):
    """Test that deleting a user releases their reservations."""
    import db

    # Reserve the page
    db.reserve_page(test_page, editor_user)

    # Verify it's reserved
    status = db.get_page_reservation_status(test_page, editor_user)
    assert status["is_reserved"] is True

    # Delete the user (ON DELETE CASCADE should handle this)
    db.delete_user(editor_user)

    # Page should have no reservation now
    # (Note: reservation record will be deleted due to CASCADE, so status check should show unreserved)
    status = db.get_page_reservation_status(test_page, None)
    assert status["is_reserved"] is False


def test_page_deleted_removes_reservation(editor_user):
    """Test that deleting a page removes its reservation."""
    import db

    page_id = db.create_page("Temp Page", "temp", "Content")
    db.reserve_page(page_id, editor_user)

    # Delete the page
    db.delete_page(page_id)

    # Reservation should be gone (CASCADE delete)
    # Verify by checking the database directly
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM page_reservations WHERE page_id=?",
        (page_id,)
    ).fetchone()
    conn.close()
    assert row is None


# ============================================================================
# PERMISSION LOSS & CLEANUP TESTS
# ============================================================================

def test_reservation_auto_released_on_role_downgrade(editor_user, editor2_user, test_page):
    """Test that a reservation is auto-released when the reserving user's role
    is downgraded from editor to user (losing edit permissions)."""
    import db

    # Editor reserves the page
    db.reserve_page(test_page, editor_user)

    status = db.get_page_reservation_status(test_page, editor2_user)
    assert status["is_reserved"] is True

    # Admin downgrades editor to user
    db.update_user(editor_user, role="user")

    # Reservation should be auto-released when checked
    status = db.get_page_reservation_status(test_page, editor2_user)
    assert status["is_reserved"] is False


def test_reservation_auto_released_allows_new_reservation(editor_user, editor2_user, test_page):
    """Test that after auto-release due to role downgrade, another user can
    reserve the same page."""
    import db

    # Editor reserves the page
    db.reserve_page(test_page, editor_user)

    # Admin downgrades editor to user
    db.update_user(editor_user, role="user")

    # Verify auto-release happened
    status = db.get_page_reservation_status(test_page, editor2_user)
    assert status["is_reserved"] is False

    # Editor2 should be able to reserve now
    reservation = db.reserve_page(test_page, editor2_user)
    assert reservation is not None
    assert reservation["user_id"] == editor2_user


def test_can_user_edit_page_after_role_downgrade(editor_user, editor2_user, test_page):
    """Test that can_user_edit_page returns True for other editors after the
    reserving user is downgraded."""
    import db

    db.reserve_page(test_page, editor_user)

    # Initially, editor2 cannot edit
    can_edit, reason = db.can_user_edit_page(test_page, editor2_user)
    assert can_edit is False

    # Downgrade editor to user
    db.update_user(editor_user, role="user")

    # Now editor2 can edit (reservation is auto-released)
    can_edit, reason = db.can_user_edit_page(test_page, editor2_user)
    assert can_edit is True


def test_cleanup_called_in_get_all_active_reservations(editor_user, test_page, monkeypatch):
    """Test that get_all_active_reservations cleans up expired entries."""
    import db

    # Create a reservation and manually expire it
    db.reserve_page(test_page, editor_user)

    # Monkey-patch time so the reservation is expired
    fake_now = datetime.now(timezone.utc) + timedelta(hours=49)
    monkeypatch.setattr(
        "db._reservations.datetime",
        type("FakeDatetime", (), {
            "now": staticmethod(lambda tz=None: fake_now),
            "fromisoformat": datetime.fromisoformat,
        })
    )

    # get_all_active_reservations should call cleanup and show no active reservations
    active = db.get_all_active_reservations()
    assert len(active) == 0

    # Verify the expired reservation was marked as released
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM page_reservations WHERE page_id=?",
        (test_page,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["released_at"] is not None


def test_admin_can_edit_page_reserved_by_editor(admin_user, editor_user, test_page):
    """Test that admins can bypass reservation locks when editing a page."""
    import db

    db.reserve_page(test_page, editor_user)

    # Admin should be able to edit even though the page is reserved by the editor
    can_edit, reason = db.can_user_edit_page(test_page, admin_user)
    assert can_edit is True
    assert reason == ""


def test_admin_can_edit_reserved_page_via_route(logged_in_admin, editor_user, test_page):
    """Test that admins can access the edit page route for a reserved page."""
    import db

    db.reserve_page(test_page, editor_user)

    # Admin should be able to GET the edit page
    resp = logged_in_admin.get("/page/test-page/edit", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Cannot edit" not in resp.data
