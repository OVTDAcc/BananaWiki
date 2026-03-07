"""
Tests for the chat / direct messaging feature.

Covers:
  - Chat creation and listing
  - Sending and viewing messages
  - Attachment upload and download (with size and count limits)
  - Admin chat monitoring (global list, per-user filter, reading chats)
  - Access control (participants only, admin override)
  - Message cleanup (nightly purge)
  - Cannot message yourself
"""

import io
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
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
def admin_uid():
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def alice_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    import db
    return db.create_user("alice", generate_password_hash("alice123"), role="user")


@pytest.fixture
def bob_uid(admin_uid):
    from werkzeug.security import generate_password_hash
    import db
    return db.create_user("bob", generate_password_hash("bob123"), role="user")


@pytest.fixture
def admin_client(client, admin_uid):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


@pytest.fixture
def alice_client(client, alice_uid):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    return client


@pytest.fixture
def bob_client(client, bob_uid):
    client.post("/login", data={"username": "bob", "password": "bob123"})
    return client


# ---------------------------------------------------------------------------
# Chat list
# ---------------------------------------------------------------------------

def test_chat_list_requires_login(client, admin_uid):
    resp = client.get("/chats")
    assert resp.status_code == 302


def test_chat_list_empty(alice_client):
    resp = alice_client.get("/chats")
    assert resp.status_code == 200
    assert b"No chats yet" in resp.data


# ---------------------------------------------------------------------------
# Start new chat
# ---------------------------------------------------------------------------

def test_new_chat_page(alice_client, bob_uid):
    resp = alice_client.get("/chats/new")
    assert resp.status_code == 200
    assert b"Start a New Chat" in resp.data


def test_start_chat_with_user(alice_client, bob_uid):
    resp = alice_client.post("/chats/new", data={"username": "bob"},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"bob" in resp.data


def test_start_chat_with_self(alice_client, alice_uid):
    resp = alice_client.post("/chats/new", data={"username": "alice"},
                             follow_redirects=True)
    assert b"cannot start a chat with yourself" in resp.data


def test_start_chat_with_nonexistent_user(alice_client, bob_uid):
    resp = alice_client.post("/chats/new", data={"username": "nobody"},
                             follow_redirects=True)
    assert b"User not found" in resp.data


def test_start_chat_empty_username(alice_client, bob_uid):
    resp = alice_client.post("/chats/new", data={"username": ""},
                             follow_redirects=True)
    assert b"Please enter a username" in resp.data


# ---------------------------------------------------------------------------
# Send messages
# ---------------------------------------------------------------------------

def test_send_message(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data={"content": "Hello Bob!"},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"Hello Bob!" in resp.data


def test_send_empty_message(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data={"content": ""},
                             follow_redirects=True)
    assert b"Message cannot be empty" in resp.data


def test_send_too_long_message(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data={"content": "x" * 5001},
                             follow_redirects=True)
    assert b"Message too long" in resp.data


def test_non_participant_cannot_send(alice_client, bob_uid, admin_uid):
    import db
    # Create a chat between bob and admin
    chat = db.get_or_create_chat(bob_uid, admin_uid)
    # Alice tries to send to it
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data={"content": "sneaky"},
                             follow_redirects=True)
    assert b"Access denied" in resp.data


# ---------------------------------------------------------------------------
# View chat
# ---------------------------------------------------------------------------

def test_view_chat(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    resp = alice_client.get(f"/chats/{chat['id']}")
    assert resp.status_code == 200
    assert b"bob" in resp.data


def test_non_participant_cannot_view(alice_client, bob_uid, admin_uid):
    import db
    chat = db.get_or_create_chat(bob_uid, admin_uid)
    resp = alice_client.get(f"/chats/{chat['id']}", follow_redirects=True)
    assert b"Access denied" in resp.data


# ---------------------------------------------------------------------------
# Chat shows in list
# ---------------------------------------------------------------------------

def test_chat_shows_in_list(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    db.send_chat_message(chat["id"], alice["id"], "Hey")
    resp = alice_client.get("/chats")
    assert resp.status_code == 200
    assert b"bob" in resp.data


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def test_send_message_with_attachment(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    data = {
        "content": "Check this out",
        "attachment": (io.BytesIO(b"file content"), "test.txt"),
    }
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"test.txt" in resp.data


def test_attachment_download(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    data = {
        "content": "Has attachment",
        "attachment": (io.BytesIO(b"hello"), "readme.txt"),
    }
    alice_client.post(f"/chats/{chat['id']}/send",
                      data=data, content_type="multipart/form-data")
    messages = db.get_chat_messages(chat["id"])
    att = messages[0]["attachments"][0]
    resp = alice_client.get(f"/chats/attachments/{att['id']}/download")
    assert resp.status_code == 200


def test_attachment_bad_extension(alice_client, bob_uid):
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    data = {
        "content": "Bad file",
        "attachment": (io.BytesIO(b"#!/bin/bash"), "evil.exe"),
    }
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert b"File type not allowed" in resp.data


def test_attachment_daily_limit(alice_client, bob_uid, monkeypatch):
    monkeypatch.setattr(config, "MAX_CHAT_ATTACHMENTS_PER_DAY", 1)
    import db
    # Also update the DB setting so the route picks up the limit
    db.update_site_settings(chat_attachments_per_day_limit=1)
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    # First attachment should work
    data = {
        "content": "First",
        "attachment": (io.BytesIO(b"a"), "a.txt"),
    }
    alice_client.post(f"/chats/{chat['id']}/send",
                      data=data, content_type="multipart/form-data")
    # Second should hit the limit
    data2 = {
        "content": "Second",
        "attachment": (io.BytesIO(b"b"), "b.txt"),
    }
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data=data2,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert b"Daily attachment limit" in resp.data


# ---------------------------------------------------------------------------
# Admin chat monitoring
# ---------------------------------------------------------------------------

def test_admin_chats_list(admin_client, alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.send_chat_message(chat["id"], alice_uid, "Hi Bob")
    resp = admin_client.get("/admin/chats")
    assert resp.status_code == 200
    assert b"alice" in resp.data
    assert b"bob" in resp.data


def test_admin_chats_filter_by_user(admin_client, alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    resp = admin_client.get(f"/admin/chats?user_id={alice_uid}")
    assert resp.status_code == 200
    assert b"alice" in resp.data


def test_admin_read_chat(admin_client, alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.send_chat_message(chat["id"], alice_uid, "Secret message")
    resp = admin_client.get(f"/admin/chats/{chat['id']}")
    assert resp.status_code == 200
    assert b"Secret message" in resp.data


def test_non_admin_cannot_access_admin_chats(alice_client, bob_uid):
    resp = alice_client.get("/admin/chats", follow_redirects=True)
    assert b"Admin access required" in resp.data


def test_admin_can_download_chat_attachment(admin_client, alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    msg_id = db.send_chat_message(chat["id"], alice_uid, "With file")
    # Write a physical file
    os.makedirs(config.CHAT_ATTACHMENT_FOLDER, exist_ok=True)
    fpath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, "testfile.txt")
    with open(fpath, "w") as f:
        f.write("content")
    db.add_chat_attachment(msg_id, "testfile.txt", "report.txt", 7)
    att = db.get_chat_messages(chat["id"])[0]["attachments"][0]
    resp = admin_client.get(f"/chats/attachments/{att['id']}/download")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def test_db_get_or_create_chat_idempotent(alice_uid, bob_uid):
    import db
    chat1 = db.get_or_create_chat(alice_uid, bob_uid)
    chat2 = db.get_or_create_chat(bob_uid, alice_uid)
    assert chat1["id"] == chat2["id"]


def test_db_is_chat_participant(alice_uid, bob_uid, admin_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    assert db.is_chat_participant(chat["id"], alice_uid)
    assert db.is_chat_participant(chat["id"], bob_uid)
    assert not db.is_chat_participant(chat["id"], admin_uid)


def test_db_chat_messages_order(alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.send_chat_message(chat["id"], alice_uid, "first")
    db.send_chat_message(chat["id"], bob_uid, "second")
    msgs = db.get_chat_messages(chat["id"])
    assert len(msgs) == 2
    assert msgs[0]["content"] == "first"
    assert msgs[1]["content"] == "second"


def test_db_cleanup_old_chat_messages(alice_uid, bob_uid):
    import db
    import sqlite3
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    msg_id = db.send_chat_message(chat["id"], alice_uid, "to be deleted")
    db.add_chat_attachment(msg_id, "stored.txt", "original.txt", 100)
    # Backdate the message so it falls outside the retention window
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.execute(
        "UPDATE chat_messages SET created_at = datetime('now', '-31 days') WHERE id = ?",
        (msg_id,)
    )
    conn.commit()
    conn.close()
    files = db.cleanup_old_chat_messages()
    assert "stored.txt" in files
    assert len(db.get_chat_messages(chat["id"])) == 0


def test_db_get_all_messages_for_backup(alice_uid, bob_uid):
    import db
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.send_chat_message(chat["id"], alice_uid, "backup me")
    msgs = db.get_all_messages_for_backup()
    assert len(msgs) == 1
    assert msgs[0]["sender_name"] == "alice"
    assert msgs[0]["receiver_name"] == "bob"


def test_attachment_oversized_file(alice_client, bob_uid, monkeypatch):
    monkeypatch.setattr(config, "MAX_CHAT_ATTACHMENT_SIZE", 10)  # 10 bytes
    import db
    alice = db.get_user_by_username("alice")
    chat = db.get_or_create_chat(alice["id"], bob_uid)
    data = {
        "content": "Big file",
        "attachment": (io.BytesIO(b"x" * 100), "big.txt"),
    }
    resp = alice_client.post(f"/chats/{chat['id']}/send",
                             data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert b"File exceeds the 5 MB limit" in resp.data
    # The text message should still exist (sent before attachment)
    msgs = db.get_chat_messages(chat["id"])
    assert len(msgs) == 1
    assert msgs[0]["content"] == "Big file"
    assert msgs[0]["attachments"] == []


def test_admin_chat_monitor_link_in_account(admin_client):
    resp = admin_client.get("/account")
    assert resp.status_code == 200
    assert b"Chat Monitor" in resp.data


# ---------------------------------------------------------------------------
# Chat disabled for DMs
# ---------------------------------------------------------------------------

def test_chat_disabled_user_cannot_start_dm(alice_uid, bob_uid):
    """A user with chat disabled should not be able to start a DM."""
    import db
    from app import app
    db.set_user_chat_disabled(alice_uid, True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "alice", "password": "alice123"})
        resp = c.get("/chats/new", follow_redirects=True)
        assert b"chat privileges have been disabled" in resp.data


def test_chat_disabled_user_cannot_send_dm(alice_uid, bob_uid):
    """A user with chat disabled should not be able to send DMs."""
    import db
    from app import app
    chat = db.get_or_create_chat(alice_uid, bob_uid)
    db.set_user_chat_disabled(alice_uid, True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "alice", "password": "alice123"})
        resp = c.post(f"/chats/{chat['id']}/send",
                      data={"content": "test"},
                      follow_redirects=True)
        assert b"chat privileges have been disabled" in resp.data
