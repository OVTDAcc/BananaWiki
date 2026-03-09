"""Tests for chat cleanup retention period feature (feature drift fix)."""
import pytest
import os
import config
import db
from datetime import datetime, timedelta


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
    db.update_site_settings(setup_done=1)
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
    old_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
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
    old_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
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
    old_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
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
