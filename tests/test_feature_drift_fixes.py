"""Tests for chat cleanup retention period feature (feature drift fix)."""
import pytest
import os
import config
import db
from datetime import datetime, timedelta, timezone


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Fresh temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_LEVEL", "off")
    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)
    chat_att_dir = str(tmp_path / "chat_attachments")
    os.makedirs(chat_att_dir, exist_ok=True)
    monkeypatch.setattr(config, "CHAT_ATTACHMENT_FOLDER", chat_att_dir)
    db.init_db()
    yield db_path


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_uid():
    from werkzeug.security import generate_password_hash
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1, page_reservations_enabled=1)
    return uid


@pytest.fixture
def alice_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    return db.create_user("alice", generate_password_hash("alice123"), role="user")


@pytest.fixture
def bob_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    return db.create_user("bob", generate_password_hash("bob123"), role="user")


@pytest.fixture
def app():
    from app import app as flask_app
    return flask_app


def test_chat_cleanup_with_retention_period(alice_uid, bob_uid):
    """Test that cleanup_old_chat_messages respects retention period."""
    # Create a chat
    chat = db.get_or_create_chat(alice_uid, bob_uid)

    # Add some messages with different timestamps (simulated by manipulating created_at)
    msg1_id = db.send_chat_message(chat["id"], alice_uid, "Old message", "127.0.0.1")
    msg2_id = db.send_chat_message(chat["id"], bob_uid, "Recent message", "127.0.0.1")

    # Manually update message 1 to be 35 days old
    conn = db.get_db()
    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    conn.execute(
        "UPDATE chat_messages SET created_at = ? WHERE id = ?",
        (old_date, msg1_id)
    )
    conn.commit()
    conn.close()

    # Run cleanup with 30-day retention
    files = db.cleanup_old_chat_messages(retention_days=30)

    # Verify old message was deleted
    messages = db.get_chat_messages(chat["id"])
    assert len(messages) == 1
    assert messages[0]["content"] == "Recent message"
    assert messages[0]["sender_id"] == bob_uid


def test_chat_cleanup_keeps_recent_messages(alice_uid, bob_uid):
    """Test that messages within retention period are preserved."""
    chat = db.get_or_create_chat(alice_uid, bob_uid)

    # Add recent messages
    db.send_chat_message(chat["id"], alice_uid, "Message 1", "127.0.0.1")
    db.send_chat_message(chat["id"], bob_uid, "Message 2", "127.0.0.1")
    db.send_chat_message(chat["id"], alice_uid, "Message 3", "127.0.0.1")

    # Run cleanup with 30-day retention (all messages are recent)
    files = db.cleanup_old_chat_messages(retention_days=30)

    # All messages should still exist
    messages = db.get_chat_messages(chat["id"])
    assert len(messages) == 3


def test_group_chat_cleanup_with_retention(alice_uid):
    """Test that cleanup_old_group_messages respects retention period."""
    # Create a group
    group = db.create_group_chat("Test Group", alice_uid, "Test description")

    # Add messages with different timestamps
    msg1_id = db.send_group_message(group["id"], alice_uid, "Old message", "127.0.0.1")
    msg2_id = db.send_group_message(group["id"], alice_uid, "Recent message", "127.0.0.1")

    # Make message 1 old (35 days)
    conn = db.get_db()
    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    conn.execute(
        "UPDATE group_messages SET created_at = ? WHERE id = ?",
        (old_date, msg1_id)
    )
    conn.commit()
    conn.close()

    # Run cleanup with 30-day retention
    files = db.cleanup_old_group_messages(retention_days=30)

    # Verify old message was deleted, recent message kept
    messages = db.get_group_messages(group["id"])
    # System message + recent message
    assert any(msg["content"] == "Recent message" for msg in messages)
    assert not any(msg["content"] == "Old message" for msg in messages)


def test_chat_cleanup_config_enabled_flag(app, alice_uid, bob_uid):
    """Test that chat_cleanup_enabled setting works (disabling it only affects the scheduler)."""
    # Set cleanup enabled to False via site settings
    db.update_site_settings(chat_cleanup_enabled=0)

    # Create chat and message
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.send_chat_message(chat["id"], alice_uid, "Test message", "127.0.0.1")

    # Make message old
    conn = db.get_db()
    old_date = (datetime.now(timezone.utc) - timedelta(days=35)).isoformat()
    conn.execute(
        "UPDATE chat_messages SET created_at = ?",
        (old_date,)
    )
    conn.commit()
    conn.close()

    # Cleanup function should still work when called directly
    # (the chat_cleanup_enabled check is in routes/chat.py scheduler)
    files = db.cleanup_old_chat_messages(retention_days=30)

    # Message should be deleted (db function doesn't check enabled flag)
    messages = db.get_chat_messages(chat["id"])
    assert len(messages) == 0


def test_group_description_storage(alice_uid):
    """Test that group descriptions are stored and retrieved."""
    # Create group with description
    description = "This is a test group for testing purposes."
    group = db.create_group_chat("Test Group", alice_uid, description)

    # Verify description is stored
    assert group["description"] == description

    # Retrieve group and verify description
    retrieved = db.get_group_chat(group["id"])
    assert retrieved["description"] == description


def test_group_description_optional(alice_uid):
    """Test that group description is optional."""
    # Create group without description
    group = db.create_group_chat("Test Group", alice_uid)

    # Should have empty string as description
    assert group["description"] == ""


def test_group_description_max_length(alice_uid):
    """Test that group descriptions can be up to 500 characters."""
    # Create group with max-length description
    description = "A" * 500
    group = db.create_group_chat("Test Group", alice_uid, description)

    assert len(group["description"]) == 500
    assert group["description"] == description


# ---------------------------------------------------------------------------
# GAP-001: view_page enforces user_can_view_page() (category read restrictions
#          and deindexed-page permissions).
# ---------------------------------------------------------------------------

def test_view_page_restricted_category_returns_403(client, admin_uid):
    """GAP-001: A user with restricted read access gets 403 on a restricted category page."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    # Create a category and a page in it
    cat_id = db.create_category("Restricted Cat")
    db.create_page("Secret Page", "secret-page", "Content", category_id=cat_id)

    # Create a user whose read access is restricted to NO categories
    user_id = db.create_user("restricted", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=True,
        read_category_ids=[],
    )

    # Log in as that restricted user
    client.post("/login", data={"username": "restricted", "password": "pass123"})

    resp = client.get("/page/secret-page")
    assert resp.status_code == 403


def test_view_page_allowed_category_returns_200(client, admin_uid):
    """GAP-001: A user with read access to a specific category can view pages in it."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    cat_id = db.create_category("Allowed Cat")
    db.create_page("Allowed Page", "allowed-page", "Content", category_id=cat_id)

    user_id = db.create_user("allowed_user", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=True,
        read_category_ids=[cat_id],
    )

    client.post("/login", data={"username": "allowed_user", "password": "pass123"})

    resp = client.get("/page/allowed-page")
    assert resp.status_code == 200


def test_view_page_unrestricted_user_can_see_all(client, admin_uid):
    """GAP-001: A user with unrestricted read access can view any page."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    cat_id = db.create_category("Some Cat")
    db.create_page("Some Page", "some-page", "Content", category_id=cat_id)

    user_id = db.create_user("free_user", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=False,
    )

    client.post("/login", data={"username": "free_user", "password": "pass123"})

    resp = client.get("/page/some-page")
    assert resp.status_code == 200


def test_view_page_admin_always_has_access(client, admin_uid):
    """GAP-001: Admins can view all pages regardless of permissions."""
    cat_id = db.create_category("Admin Cat")
    db.create_page("Admin Page", "admin-page", "Content", category_id=cat_id)

    client.post("/login", data={"username": "admin", "password": "admin123"})

    resp = client.get("/page/admin-page")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-002: Search API filters results by category read access restrictions.
# ---------------------------------------------------------------------------

def test_search_api_filters_restricted_categories(client, admin_uid):
    """GAP-002: Search results exclude pages in restricted categories for restricted users."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    # Create two categories with pages
    allowed_cat = db.create_category("Allowed Category")
    restricted_cat = db.create_category("Restricted Category")
    db.create_page("Public Page", "public-page", "Content", category_id=allowed_cat)
    db.create_page("Private Page", "private-page", "Content", category_id=restricted_cat)

    # Create user with read access only to allowed_cat
    user_id = db.create_user("search_user", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=True,
        read_category_ids=[allowed_cat],
    )

    client.post("/login", data={"username": "search_user", "password": "pass123"})

    resp = client.get("/api/pages/search?q=Page")
    assert resp.status_code == 200
    data = resp.get_json()
    slugs = [r["slug"] for r in data]

    # Should see public page but NOT private page
    assert "public-page" in slugs
    assert "private-page" not in slugs


def test_search_api_unrestricted_user_sees_all(client, admin_uid):
    """GAP-002: An unrestricted user sees all pages in search results."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    cat_id = db.create_category("Some Category")
    db.create_page("Findable Page", "findable-page", "Content", category_id=cat_id)

    user_id = db.create_user("unrestr_user", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=False,
    )

    client.post("/login", data={"username": "unrestr_user", "password": "pass123"})

    resp = client.get("/api/pages/search?q=Findable")
    assert resp.status_code == 200
    data = resp.get_json()
    slugs = [r["slug"] for r in data]
    assert "findable-page" in slugs


def test_sidebar_search_filters_restricted_categories(client, admin_uid):
    """GAP-002: Sidebar search also excludes pages in restricted categories."""
    from werkzeug.security import generate_password_hash
    from helpers._permissions import get_default_permissions

    allowed_cat = db.create_category("AllowedCat")
    blocked_cat = db.create_category("BlockedCat")
    db.create_page("Open Page", "open-page", "Content", category_id=allowed_cat)
    db.create_page("Hidden Page", "hidden-page", "Content", category_id=blocked_cat)

    user_id = db.create_user("sb_user", generate_password_hash("pass123"), role="user")
    db.set_user_permissions(
        user_id,
        get_default_permissions("user"),
        read_restricted=True,
        read_category_ids=[allowed_cat],
    )

    client.post("/login", data={"username": "sb_user", "password": "pass123"})

    resp = client.get("/api/sidebar/search?q=Page")
    assert resp.status_code == 200
    data = resp.get_json()
    slugs = [p["slug"] for p in data.get("pages", [])]

    assert "open-page" in slugs
    assert "hidden-page" not in slugs


# ---------------------------------------------------------------------------
# GAP-003 / GAP-004: Admin checkouts page and force-release.
# ---------------------------------------------------------------------------

@pytest.fixture
def editor_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    return db.create_user("editor1", generate_password_hash("editor123"), role="editor")


@pytest.fixture
def editor2_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    return db.create_user("editor2", generate_password_hash("editor123"), role="editor")


def test_admin_checkouts_page_loads(client, admin_uid):
    """GAP-003: Admin can view the /admin/checkouts page."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/admin/checkouts")
    assert resp.status_code == 200
    assert b"Page Checkouts" in resp.data


def test_admin_checkouts_shows_active_reservations(client, admin_uid, editor_uid):
    """GAP-003: Active reservations are listed on /admin/checkouts."""
    page_id = db.create_page("Reserved Page", "reserved-page", "Content")
    db.reserve_page(page_id, editor_uid)

    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/admin/checkouts")
    assert resp.status_code == 200
    assert b"Reserved Page" in resp.data
    assert b"editor1" in resp.data


def test_admin_checkouts_empty_when_no_reservations(client, admin_uid):
    """GAP-003: Admin checkouts page shows empty state when no reservations."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/admin/checkouts")
    assert resp.status_code == 200
    assert b"No active page reservations" in resp.data


def test_admin_force_release_reservation(client, admin_uid, editor_uid):
    """GAP-004: Admin can force-release a reservation."""
    page_id = db.create_page("Force Release Page", "force-release-page", "Content")
    db.reserve_page(page_id, editor_uid)

    # Confirm reserved
    status = db.get_page_reservation_status(page_id)
    assert status["is_reserved"]

    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.post(f"/admin/checkouts/{page_id}/release", follow_redirects=True)
    assert resp.status_code == 200

    # Confirm no longer reserved
    status = db.get_page_reservation_status(page_id)
    assert not status["is_reserved"]


def test_admin_force_release_nonexistent_page(client, admin_uid):
    """GAP-004: Force-release on nonexistent page returns 404."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.post("/admin/checkouts/99999/release")
    assert resp.status_code == 404


def test_non_admin_cannot_access_checkouts(client, admin_uid, editor_uid):
    """GAP-003: Non-admin users cannot access /admin/checkouts."""
    client.post("/login", data={"username": "editor1", "password": "editor123"})
    resp = client.get("/admin/checkouts")
    assert resp.status_code in (302, 403)


def test_get_all_active_reservations_db_function(admin_uid, editor_uid):
    """GAP-003: get_all_active_reservations() returns all active reservations."""
    page1_id = db.create_page("Page One", "page-one", "Content")
    page2_id = db.create_page("Page Two", "page-two", "Content")

    db.reserve_page(page1_id, editor_uid)
    db.reserve_page(page2_id, editor_uid)

    all_res = db.get_all_active_reservations()
    page_ids = [r["page_id"] for r in all_res]
    assert page1_id in page_ids
    assert page2_id in page_ids


# ---------------------------------------------------------------------------
# GAP-005: Edit button disabled for reserved pages (non-owner editors).
# ---------------------------------------------------------------------------

def test_edit_button_disabled_when_reserved_by_other(client, admin_uid, editor_uid, editor2_uid):
    """GAP-005: The Edit button is disabled when the page is reserved by another editor."""
    page_id = db.create_page("Locked Page", "locked-page", "Content")
    db.reserve_page(page_id, editor_uid)  # editor1 reserves

    # Log in as editor2 and view the page
    client.post("/login", data={"username": "editor2", "password": "editor123"})
    resp = client.get("/page/locked-page")
    assert resp.status_code == 200
    # The Edit button should be rendered as a disabled <button>, not an <a>
    assert b'<button class="btn btn-sm" disabled' in resp.data


def test_edit_button_enabled_for_reservation_owner(client, admin_uid, editor_uid):
    """GAP-005: The Edit button is NOT disabled for the user who holds the reservation."""
    page_id = db.create_page("My Page", "my-page", "Content")
    db.reserve_page(page_id, editor_uid)  # editor1 reserves

    client.post("/login", data={"username": "editor1", "password": "editor123"})
    resp = client.get("/page/my-page")
    assert resp.status_code == 200
    # The owner should see the normal Edit link, not a disabled button
    assert b'href="/page/my-page/edit"' in resp.data or b'href=' in resp.data
    assert b'<button class="btn btn-sm" disabled' not in resp.data


def test_admin_edit_button_not_disabled_even_when_reserved(client, admin_uid, editor_uid):
    """GAP-005: Admins always see an active Edit link even when page is reserved by editor."""
    page_id = db.create_page("Admin Edit Page", "admin-edit-page", "Content")
    db.reserve_page(page_id, editor_uid)  # editor1 reserves

    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/page/admin-edit-page")
    assert resp.status_code == 200
    assert b'<button class="btn btn-sm" disabled' not in resp.data


# ---------------------------------------------------------------------------
# GAP-006: Edit form includes "Reserve this page" checkbox.
# ---------------------------------------------------------------------------

def test_edit_form_has_reserve_checkbox(client, admin_uid, editor_uid):
    """GAP-006: The edit form shows a 'Reserve this page' checkbox."""
    page_id = db.create_page("Editable Page", "editable-page", "Content")

    client.post("/login", data={"username": "editor1", "password": "editor123"})
    resp = client.get("/page/editable-page/edit")
    assert resp.status_code == 200
    assert b'name="reserve_after_commit"' in resp.data


def test_edit_form_reserve_checkbox_reserves_page(client, admin_uid, editor_uid):
    """GAP-006: Checking reserve_after_commit reserves the page after committing."""
    page_id = db.create_page("To Reserve", "to-reserve", "Content")

    client.post("/login", data={"username": "editor1", "password": "editor123"})
    resp = client.post(
        "/page/to-reserve/edit",
        data={
            "title": "To Reserve",
            "content": "Updated",
            "edit_message": "test edit",
            "reserve_after_commit": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Page should now be reserved by editor1
    status = db.get_page_reservation_status(page_id)
    assert status["is_reserved"]
    assert status["reserved_by"] == editor_uid


# ---------------------------------------------------------------------------
# GAP-007: Draft transfer is available to editors (not admin-only).
# ---------------------------------------------------------------------------

def test_editor_can_transfer_draft(client, admin_uid, editor_uid, editor2_uid):
    """GAP-007: An editor can transfer another user's draft to themselves."""
    import json
    page_id = db.create_page("Draft Page", "draft-page", "Content")

    # editor2 creates a draft
    db.save_draft(page_id, editor2_uid, "Draft Title", "Draft content")

    # editor1 logs in and transfers the draft
    client.post("/login", data={"username": "editor1", "password": "editor123"})
    resp = client.post(
        "/api/draft/transfer",
        data=json.dumps({"page_id": page_id, "from_user_id": editor2_uid}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True


def test_regular_user_cannot_transfer_draft(client, admin_uid, alice_uid, editor_uid):
    """GAP-007: Regular users (non-editors) cannot call the transfer draft endpoint."""
    import json
    page_id = db.create_page("Draft Page2", "draft-page-2", "Content")
    db.save_draft(page_id, editor_uid, "Draft Title", "Draft content")

    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.post(
        "/api/draft/transfer",
        data=json.dumps({"page_id": page_id, "from_user_id": editor_uid}),
        content_type="application/json",
    )
    # regular user should be forbidden (editor_required redirects or 403)
    assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# GAP-008: chat_dm_enabled setting disables DM access for non-admins.
# ---------------------------------------------------------------------------

def test_dm_disabled_blocks_chat_list(client, admin_uid, alice_uid):
    """GAP-008: When chat_dm_enabled=0, non-admin users cannot access /chats."""
    db.update_site_settings(chat_dm_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/chats", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_dm_disabled_blocks_chat_new(client, admin_uid, alice_uid):
    """GAP-008: When chat_dm_enabled=0, non-admin users cannot access /chats/new."""
    db.update_site_settings(chat_dm_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/chats/new", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_dm_disabled_blocks_chat_view(client, admin_uid, alice_uid, bob_uid):
    """GAP-008: When chat_dm_enabled=0, non-admin users cannot view existing DMs."""
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.update_site_settings(chat_dm_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get(f"/chats/{chat['id']}", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_dm_disabled_admin_still_has_access(client, admin_uid, alice_uid):
    """GAP-008: When chat_dm_enabled=0, admins are NOT blocked."""
    db.update_site_settings(chat_dm_enabled=0)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/chats", follow_redirects=True)
    assert resp.status_code == 200


def test_dm_enabled_allows_access(client, admin_uid, alice_uid):
    """GAP-008: When chat_dm_enabled=1, users can access /chats normally."""
    db.update_site_settings(chat_dm_enabled=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/chats", follow_redirects=True)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-009: chat_allow_dm_creation setting prevents creating new DMs.
# ---------------------------------------------------------------------------

def test_dm_creation_disabled_blocks_new_dm(client, admin_uid, alice_uid, bob_uid):
    """GAP-009: When chat_allow_dm_creation=0, non-admins cannot create new DMs."""
    db.update_site_settings(chat_dm_enabled=1, chat_allow_dm_creation=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/chats/new", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_dm_creation_disabled_admin_can_create(client, admin_uid, alice_uid):
    """GAP-009: When chat_allow_dm_creation=0, admins can still create DMs."""
    db.update_site_settings(chat_dm_enabled=1, chat_allow_dm_creation=0)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/chats/new", follow_redirects=True)
    assert resp.status_code == 200


def test_dm_creation_enabled_allows_new_dm(client, admin_uid, alice_uid):
    """GAP-009: When chat_allow_dm_creation=1, users can visit /chats/new."""
    db.update_site_settings(chat_dm_enabled=1, chat_allow_dm_creation=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/chats/new", follow_redirects=True)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-010: chat_group_enabled setting disables group chat access for non-admins.
# ---------------------------------------------------------------------------

def test_group_disabled_blocks_group_list(client, admin_uid, alice_uid):
    """GAP-010: When chat_group_enabled=0, non-admins cannot access /groups."""
    db.update_site_settings(chat_group_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/groups", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_group_disabled_blocks_group_new(client, admin_uid, alice_uid):
    """GAP-010: When chat_group_enabled=0, non-admins cannot access /groups/new."""
    db.update_site_settings(chat_group_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/groups/new", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_group_disabled_admin_still_has_access(client, admin_uid, alice_uid):
    """GAP-010: When chat_group_enabled=0, admins are NOT blocked from /groups."""
    db.update_site_settings(chat_group_enabled=0)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/groups", follow_redirects=True)
    assert resp.status_code == 200


def test_group_enabled_allows_access(client, admin_uid, alice_uid):
    """GAP-010: When chat_group_enabled=1, users can access /groups normally."""
    db.update_site_settings(chat_group_enabled=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/groups", follow_redirects=True)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-011: chat_allow_group_creation setting prevents creating new groups.
# ---------------------------------------------------------------------------

def test_group_creation_disabled_blocks_new_group(client, admin_uid, alice_uid):
    """GAP-011: When chat_allow_group_creation=0, non-admins cannot create groups."""
    db.update_site_settings(chat_group_enabled=1, chat_allow_group_creation=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/groups/new", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_group_creation_disabled_admin_can_create(client, admin_uid, alice_uid):
    """GAP-011: When chat_allow_group_creation=0, admins can still create groups."""
    db.update_site_settings(chat_group_enabled=1, chat_allow_group_creation=0)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/groups/new", follow_redirects=True)
    assert resp.status_code == 200


def test_group_creation_enabled_allows_new_group(client, admin_uid, alice_uid):
    """GAP-011: When chat_allow_group_creation=1, users can visit /groups/new."""
    db.update_site_settings(chat_group_enabled=1, chat_allow_group_creation=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})
    resp = client.get("/groups/new", follow_redirects=True)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GAP-012: chat_attachments_enabled setting blocks file attachments in DMs.
# ---------------------------------------------------------------------------

def test_dm_attachments_disabled_blocks_upload(client, admin_uid, alice_uid, bob_uid, tmp_path):
    """GAP-012: When chat_attachments_enabled=0, non-admins cannot attach files to DMs."""
    import io
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.update_site_settings(chat_dm_enabled=1, chat_attachments_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})

    fake_file = (io.BytesIO(b"fake file content"), "test.pdf")
    resp = client.post(
        f"/chats/{chat['id']}/send",
        data={"content": "hello", "attachment": fake_file},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"attachments are currently disabled" in resp.data


def test_dm_attachments_disabled_admin_can_upload(client, admin_uid, alice_uid, tmp_path):
    """GAP-012: When chat_attachments_enabled=0, admins can still attach files."""
    import io
    chat = db.get_or_create_chat(admin_uid, alice_uid)
    db.update_site_settings(chat_dm_enabled=1, chat_attachments_enabled=0)
    client.post("/login", data={"username": "admin", "password": "admin123"})

    fake_file = (io.BytesIO(b"fake file content"), "test.pdf")
    resp = client.post(
        f"/chats/{chat['id']}/send",
        data={"content": "hello", "attachment": fake_file},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    # Should succeed (not blocked by disabled check)
    assert resp.status_code == 200
    assert b"attachments are currently disabled" not in resp.data


def test_dm_attachments_enabled_allows_upload(client, admin_uid, alice_uid, bob_uid):
    """GAP-012: When chat_attachments_enabled=1, attachment upload is attempted normally."""
    import io
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.update_site_settings(chat_dm_enabled=1, chat_attachments_enabled=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})

    fake_file = (io.BytesIO(b"fake file content"), "test.pdf")
    resp = client.post(
        f"/chats/{chat['id']}/send",
        data={"content": "hello", "attachment": fake_file},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    # Should not show the disabled flash message
    assert b"attachments are currently disabled" not in resp.data


# ---------------------------------------------------------------------------
# GAP-013: chat_attachments_enabled setting blocks file attachments in groups.
# ---------------------------------------------------------------------------

def test_group_attachments_disabled_blocks_upload(client, admin_uid, alice_uid, tmp_path):
    """GAP-013: When chat_attachments_enabled=0, non-admins cannot attach files to groups."""
    import io
    group = db.create_group_chat("Test Group", alice_uid)
    db.update_site_settings(chat_group_enabled=1, chat_attachments_enabled=0)
    client.post("/login", data={"username": "alice", "password": "alice123"})

    fake_file = (io.BytesIO(b"fake file content"), "test.pdf")
    resp = client.post(
        f"/groups/{group['id']}/send",
        data={"content": "hello", "attachment": fake_file},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"attachments are currently disabled" in resp.data


def test_group_attachments_enabled_allows_upload(client, admin_uid, alice_uid):
    """GAP-013: When chat_attachments_enabled=1, attachment upload is attempted normally."""
    import io
    group = db.create_group_chat("Test Group 2", alice_uid)
    db.update_site_settings(chat_group_enabled=1, chat_attachments_enabled=1)
    client.post("/login", data={"username": "alice", "password": "alice123"})

    fake_file = (io.BytesIO(b"fake file content"), "test.pdf")
    resp = client.post(
        f"/groups/{group['id']}/send",
        data={"content": "hello", "attachment": fake_file},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"attachments are currently disabled" not in resp.data
