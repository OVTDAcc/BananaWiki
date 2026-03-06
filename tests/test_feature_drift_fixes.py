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


def test_chat_cleanup_config_enabled_flag(app, alice_uid, bob_uid, monkeypatch):
    """Test that CHAT_CLEANUP_ENABLED configuration works."""
    # Set cleanup enabled to False
    monkeypatch.setattr(config, "CHAT_CLEANUP_ENABLED", False)

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
    # (the ENABLED check is in routes/chat.py scheduler)
    files = db.cleanup_old_chat_messages(retention_days=30)

    # Message should be deleted (db function doesn't check ENABLED flag)
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
