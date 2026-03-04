"""
Tests for the group chat feature.

Covers:
  - Group creation and listing
  - Joining groups (invite code and direct add)
  - Global chat (auto-created, auto-join)
  - Sending and viewing messages
  - System messages for events
  - Moderation: timeout, untimeout, delete messages
  - Ownership: promote, demote, transfer
  - Access control (members only, role restrictions)
  - Attachment upload and download
  - Admin group monitoring
  - Leaving groups
  - Database helpers (cleanup, backup)
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
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
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
# Group list
# ---------------------------------------------------------------------------

def test_group_list_requires_login(client, admin_uid):
    resp = client.get("/groups")
    assert resp.status_code == 302


def test_group_list_empty(alice_client):
    resp = alice_client.get("/groups")
    assert resp.status_code == 200
    assert b"No groups yet" in resp.data


# ---------------------------------------------------------------------------
# Create group
# ---------------------------------------------------------------------------

def test_create_group_page(alice_client):
    resp = alice_client.get("/groups/new")
    assert resp.status_code == 200
    assert b"Create a New Group" in resp.data


def test_create_group(alice_client):
    resp = alice_client.post("/groups/new", data={"name": "Test Group"},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"Test Group" in resp.data


def test_create_group_empty_name(alice_client):
    resp = alice_client.post("/groups/new", data={"name": ""},
                             follow_redirects=True)
    assert b"Group name is required" in resp.data


def test_create_group_too_long_name(alice_client):
    resp = alice_client.post("/groups/new", data={"name": "x" * 101},
                             follow_redirects=True)
    assert b"Group name too long" in resp.data


def test_create_group_system_message(alice_client, alice_uid):
    import db
    alice_client.post("/groups/new", data={"name": "My Group"})
    groups = db.get_user_groups(alice_uid)
    assert len(groups) == 1
    messages = db.get_group_messages(groups[0]["id"])
    assert any(m["is_system"] and "created the group" in m["content"] for m in messages)


def test_creator_is_owner(alice_client, alice_uid):
    import db
    alice_client.post("/groups/new", data={"name": "Owned Group"})
    groups = db.get_user_groups(alice_uid)
    member = db.get_group_member(groups[0]["id"], alice_uid)
    assert member["role"] == "owner"


# ---------------------------------------------------------------------------
# Join group
# ---------------------------------------------------------------------------

def test_join_group_page(alice_client):
    resp = alice_client.get("/groups/join")
    assert resp.status_code == 200
    assert b"Join a Group" in resp.data


def test_join_group_with_code(alice_client, bob_uid):
    import db
    group = db.create_group_chat("Bob's Group", bob_uid)
    resp = alice_client.post("/groups/join",
                             data={"invite_code": group["invite_code"]},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"Bob&#39;s Group" in resp.data or b"Bob's Group" in resp.data


def test_join_group_invalid_code(alice_client):
    resp = alice_client.post("/groups/join",
                             data={"invite_code": "BADCODE1"},
                             follow_redirects=True)
    assert b"Invalid invite code" in resp.data


def test_join_group_empty_code(alice_client):
    resp = alice_client.post("/groups/join",
                             data={"invite_code": ""},
                             follow_redirects=True)
    assert b"Please enter an invite code" in resp.data


def test_join_group_already_member(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Alice's Group", alice_uid)
    resp = alice_client.post("/groups/join",
                             data={"invite_code": group["invite_code"]},
                             follow_redirects=True)
    assert b"already a member" in resp.data


def test_join_group_system_message(alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.send_group_system_message(group["id"], "bob joined the group")
    messages = db.get_group_messages(group["id"])
    system_msgs = [m for m in messages if m["is_system"]]
    assert any("bob joined" in m["content"] for m in system_msgs)


# ---------------------------------------------------------------------------
# Global chat
# ---------------------------------------------------------------------------

def test_global_chat_auto_join(alice_client, alice_uid):
    resp = alice_client.get("/groups/global", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Global Chat" in resp.data


def test_global_chat_idempotent(alice_uid, bob_uid):
    import db
    g1 = db.get_or_create_global_chat()
    g2 = db.get_or_create_global_chat()
    assert g1["id"] == g2["id"]


def test_global_chat_shown_in_groups(alice_client, alice_uid):
    alice_client.get("/groups/global", follow_redirects=True)
    resp = alice_client.get("/groups")
    assert b"Global Chat" in resp.data


# ---------------------------------------------------------------------------
# Send messages
# ---------------------------------------------------------------------------

def test_send_group_message(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data={"content": "Hello Group!"},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"Hello Group!" in resp.data


def test_send_empty_group_message(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data={"content": ""},
                             follow_redirects=True)
    assert b"Message cannot be empty" in resp.data


def test_send_too_long_group_message(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data={"content": "x" * 5001},
                             follow_redirects=True)
    assert b"Message too long" in resp.data


def test_non_member_cannot_send(alice_client, bob_uid):
    import db
    group = db.create_group_chat("Bob Only", bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data={"content": "sneaky"},
                             follow_redirects=True)
    assert b"Access denied" in resp.data


def test_timed_out_cannot_send(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", bob_uid)
    db.add_group_member(group["id"], alice_uid)
    db.set_group_member_timeout(group["id"], alice_uid, "9999-12-31T23:59:59+00:00")
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data={"content": "trying"},
                             follow_redirects=True)
    assert b"timed out" in resp.data


# ---------------------------------------------------------------------------
# View group
# ---------------------------------------------------------------------------

def test_view_group(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.get(f"/groups/{group['id']}")
    assert resp.status_code == 200
    assert b"Test" in resp.data


def test_non_member_cannot_view(alice_client, bob_uid):
    import db
    group = db.create_group_chat("Private", bob_uid)
    resp = alice_client.get(f"/groups/{group['id']}", follow_redirects=True)
    assert b"not a member" in resp.data


# ---------------------------------------------------------------------------
# Group shows in list
# ---------------------------------------------------------------------------

def test_group_shows_in_list(alice_client, alice_uid):
    import db
    group = db.create_group_chat("My Group", alice_uid)
    db.send_group_message(group["id"], alice_uid, "Hey team")
    resp = alice_client.get("/groups")
    assert b"My Group" in resp.data


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------

def test_send_group_message_with_attachment(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    data = {
        "content": "Check this out",
        "attachment": (io.BytesIO(b"file content"), "test.txt"),
    }
    resp = alice_client.post(f"/groups/{group['id']}/send",
                             data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"test.txt" in resp.data


def test_group_attachment_download(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    data = {
        "content": "Has attachment",
        "attachment": (io.BytesIO(b"hello"), "readme.txt"),
    }
    alice_client.post(f"/groups/{group['id']}/send",
                      data=data, content_type="multipart/form-data")
    messages = db.get_group_messages(group["id"])
    # Find the user message (not system)
    user_msgs = [m for m in messages if not m["is_system"]]
    att = user_msgs[0]["attachments"][0]
    resp = alice_client.get(f"/groups/attachments/{att['id']}/download")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Moderation – Add member
# ---------------------------------------------------------------------------

def test_add_member_to_group(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.post(f"/groups/{group['id']}/members/add",
                             data={"username": "bob"},
                             follow_redirects=True)
    assert b"bob" in resp.data
    assert b"has been added" in resp.data


def test_non_mod_cannot_add_member(alice_uid, bob_uid):
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/members/add",
                      data={"username": "admin"},
                      follow_redirects=True)
        assert b"do not have permission" in resp.data


# ---------------------------------------------------------------------------
# Moderation – Delete message
# ---------------------------------------------------------------------------

def test_owner_can_delete_message(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    msg_id = db.send_group_message(group["id"], bob_uid, "delete me")
    resp = alice_client.post(f"/groups/{group['id']}/delete_message",
                             data={"message_id": msg_id},
                             follow_redirects=True)
    assert b"Message deleted" in resp.data
    messages = db.get_group_messages(group["id"])
    user_msgs = [m for m in messages if not m["is_system"]]
    assert not any(m["content"] == "delete me" for m in user_msgs)


def test_member_cannot_delete_message(alice_uid, bob_uid):
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    msg_id = db.send_group_message(group["id"], alice_uid, "keep me")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/delete_message",
                      data={"message_id": msg_id},
                      follow_redirects=True)
        assert b"Permission denied" in resp.data


# ---------------------------------------------------------------------------
# Moderation – Timeout
# ---------------------------------------------------------------------------

def test_timeout_member(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/timeout",
                             data={"user_id": bob_uid, "duration": "30"},
                             follow_redirects=True)
    assert b"timed out" in resp.data
    assert db.is_group_member_timed_out(group["id"], bob_uid)


def test_untimeout_member(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.set_group_member_timeout(group["id"], bob_uid, "9999-12-31T23:59:59+00:00")
    resp = alice_client.post(f"/groups/{group['id']}/untimeout",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"timeout has been removed" in resp.data
    assert not db.is_group_member_timed_out(group["id"], bob_uid)


def test_indefinite_timeout(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/timeout",
                             data={"user_id": bob_uid, "duration": "indefinite"},
                             follow_redirects=True)
    assert b"timed out" in resp.data
    assert db.is_group_member_timed_out(group["id"], bob_uid)


def test_mod_cannot_timeout_owner(alice_uid, bob_uid):
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid, role="moderator")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/timeout",
                      data={"user_id": alice_uid, "duration": "30"},
                      follow_redirects=True)
        assert b"cannot timeout" in resp.data


# ---------------------------------------------------------------------------
# Ownership – Promote / Demote
# ---------------------------------------------------------------------------

def test_promote_member(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/promote",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"now a moderator" in resp.data
    assert db.get_group_member_role(group["id"], bob_uid) == "moderator"


def test_demote_moderator(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid, role="moderator")
    resp = alice_client.post(f"/groups/{group['id']}/demote",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"no longer a moderator" in resp.data
    assert db.get_group_member_role(group["id"], bob_uid) == "member"


def test_non_owner_cannot_promote(alice_uid, bob_uid):
    import db
    from werkzeug.security import generate_password_hash
    from app import app
    charlie_uid = db.create_user("charlie", generate_password_hash("charlie123"), role="user")
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid, role="moderator")
    db.add_group_member(group["id"], charlie_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/promote",
                      data={"user_id": charlie_uid},
                      follow_redirects=True)
        assert b"Only the group owner" in resp.data


# ---------------------------------------------------------------------------
# Ownership – Transfer
# ---------------------------------------------------------------------------

def test_transfer_ownership(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/transfer",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"Ownership transferred" in resp.data
    assert db.get_group_member_role(group["id"], bob_uid) == "owner"
    assert db.get_group_member_role(group["id"], alice_uid) == "moderator"


def test_cannot_transfer_global_chat(admin_client, admin_uid, alice_uid):
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    db.add_group_member(group["id"], alice_uid)
    db.set_group_member_role(group["id"], admin_uid, "owner")
    resp = admin_client.post(f"/groups/{group['id']}/transfer",
                             data={"user_id": alice_uid},
                             follow_redirects=True)
    assert b"Cannot transfer" in resp.data


# ---------------------------------------------------------------------------
# Leave group
# ---------------------------------------------------------------------------

def test_member_can_leave(alice_uid, bob_uid):
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/leave", follow_redirects=True)
        assert b"You left the group" in resp.data
    assert not db.is_group_member(group["id"], bob_uid)


def test_owner_cannot_leave_without_transfer(alice_client, alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = alice_client.post(f"/groups/{group['id']}/leave",
                             follow_redirects=True)
    assert b"must transfer ownership" in resp.data


# ---------------------------------------------------------------------------
# Kick member
# ---------------------------------------------------------------------------

def test_owner_can_kick(alice_client, alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/kick",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"has been removed" in resp.data
    assert not db.is_group_member(group["id"], bob_uid)


def test_mod_cannot_kick_owner(alice_uid, bob_uid):
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid, role="moderator")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/kick",
                      data={"user_id": alice_uid},
                      follow_redirects=True)
        assert b"cannot remove" in resp.data


# ---------------------------------------------------------------------------
# Admin monitoring
# ---------------------------------------------------------------------------

def test_admin_groups_list(admin_client, alice_uid):
    import db
    db.create_group_chat("AdminTest", alice_uid)
    resp = admin_client.get("/admin/groups")
    assert resp.status_code == 200
    assert b"AdminTest" in resp.data


def test_admin_group_view(admin_client, alice_uid):
    import db
    group = db.create_group_chat("AdminView", alice_uid)
    db.send_group_message(group["id"], alice_uid, "Secret group msg")
    resp = admin_client.get(f"/admin/groups/{group['id']}")
    assert resp.status_code == 200
    assert b"Secret group msg" in resp.data


def test_non_admin_cannot_access_admin_groups(alice_client):
    resp = alice_client.get("/admin/groups", follow_redirects=True)
    assert b"Admin access required" in resp.data


def test_admin_group_monitor_link_in_account(admin_client):
    resp = admin_client.get("/account")
    assert resp.status_code == 200
    assert b"Group Monitor" in resp.data


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def test_db_create_group_has_invite_code(alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    assert group["invite_code"]
    assert len(group["invite_code"]) == 8


def test_db_get_group_by_invite(alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    found = db.get_group_chat_by_invite(group["invite_code"])
    assert found["id"] == group["id"]


def test_db_group_membership(alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    assert db.is_group_member(group["id"], alice_uid)
    assert not db.is_group_member(group["id"], bob_uid)
    db.add_group_member(group["id"], bob_uid)
    assert db.is_group_member(group["id"], bob_uid)


def test_db_group_message_order(alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.send_group_message(group["id"], alice_uid, "first")
    db.send_group_message(group["id"], bob_uid, "second")
    msgs = db.get_group_messages(group["id"])
    # Filter non-system messages
    user_msgs = [m for m in msgs if not m["is_system"]]
    assert user_msgs[0]["content"] == "first"
    assert user_msgs[1]["content"] == "second"


def test_db_cleanup_group_messages(alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    msg_id = db.send_group_message(group["id"], alice_uid, "to be deleted")
    db.add_group_attachment(msg_id, "stored.txt", "original.txt", 100)
    files = db.cleanup_old_group_messages()
    assert "stored.txt" in files
    msgs = db.get_group_messages(group["id"])
    assert len(msgs) == 0


def test_db_group_backup(alice_uid):
    import db
    group = db.create_group_chat("Backup Test", alice_uid)
    db.send_group_message(group["id"], alice_uid, "backup me")
    msgs = db.get_all_group_messages_for_backup()
    assert len(msgs) >= 1
    user_msgs = [m for m in msgs if m["content"] == "backup me"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["group_name"] == "Backup Test"


def test_db_timeout_expired(alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    # Set timeout in the past
    db.set_group_member_timeout(group["id"], bob_uid, "2020-01-01T00:00:00+00:00")
    assert not db.is_group_member_timed_out(group["id"], bob_uid)


def test_db_timeout_no_timeout(alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    assert not db.is_group_member_timed_out(group["id"], alice_uid)


def test_db_delete_group_message(alice_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    msg_id = db.send_group_message(group["id"], alice_uid, "to delete")
    db.add_group_attachment(msg_id, "del.txt", "del.txt", 50)
    files = db.delete_group_message(msg_id)
    assert "del.txt" in files
    assert db.get_group_message_by_id(msg_id) is None


def test_db_transfer_ownership(alice_uid, bob_uid):
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.transfer_group_ownership(group["id"], alice_uid, bob_uid)
    assert db.get_group_member_role(group["id"], bob_uid) == "owner"
    assert db.get_group_member_role(group["id"], alice_uid) == "moderator"
    updated = db.get_group_chat(group["id"])
    assert updated["creator_id"] == bob_uid


# ---------------------------------------------------------------------------
# Global chat moderation by site admin
# ---------------------------------------------------------------------------

def test_site_admin_can_delete_global_msg(admin_client, admin_uid, alice_uid):
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    db.add_group_member(group["id"], alice_uid)
    msg_id = db.send_group_message(group["id"], alice_uid, "bad msg")
    resp = admin_client.post(f"/groups/{group['id']}/delete_message",
                             data={"message_id": msg_id},
                             follow_redirects=True)
    assert b"Message deleted" in resp.data


def test_site_admin_can_timeout_in_global(admin_client, admin_uid, alice_uid):
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    db.add_group_member(group["id"], alice_uid)
    resp = admin_client.post(f"/groups/{group['id']}/timeout",
                             data={"user_id": alice_uid, "duration": "5"},
                             follow_redirects=True)
    assert b"timed out" in resp.data


def test_non_admin_cannot_moderate_global(alice_uid, bob_uid):
    import db
    from app import app
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], alice_uid)
    db.add_group_member(group["id"], bob_uid)
    msg_id = db.send_group_message(group["id"], bob_uid, "innocent msg")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "alice", "password": "alice123"})
        resp = c.post(f"/groups/{group['id']}/delete_message",
                      data={"message_id": msg_id},
                      follow_redirects=True)
        assert b"Only site admins" in resp.data


# ---------------------------------------------------------------------------
# Edge cases (verification fixes)
# ---------------------------------------------------------------------------

def test_untimeout_non_member_rejected(alice_client, alice_uid, bob_uid):
    """Untimeout should fail if target is not a member of the group."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    # bob is NOT a member
    resp = alice_client.post(f"/groups/{group['id']}/untimeout",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"User is not a member" in resp.data


def test_expired_timeout_icon_not_shown(alice_client, alice_uid, bob_uid):
    """Expired timeout should not show the ⏳ icon in the member list."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    # Set timeout in the past
    db.set_group_member_timeout(group["id"], bob_uid, "2020-01-01T00:00:00+00:00")
    resp = alice_client.get(f"/groups/{group['id']}")
    assert resp.status_code == 200
    # The ⏳ icon should NOT appear for expired timeouts
    assert "⏳".encode() not in resp.data


def test_active_timeout_icon_shown(alice_client, alice_uid, bob_uid):
    """Active timeout should show the ⏳ icon in the member list."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    # Set timeout far in the future
    db.set_group_member_timeout(group["id"], bob_uid, "9999-12-31T23:59:59+00:00")
    resp = alice_client.get(f"/groups/{group['id']}")
    assert resp.status_code == 200
    assert "⏳".encode() in resp.data


def test_untimeout_system_message_grammar(alice_client, alice_uid, bob_uid):
    """System message for untimeout should use proper grammar."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.set_group_member_timeout(group["id"], bob_uid, "9999-12-31T23:59:59+00:00")
    alice_client.post(f"/groups/{group['id']}/untimeout",
                      data={"user_id": bob_uid},
                      follow_redirects=True)
    messages = db.get_group_messages(group["id"])
    sys_msgs = [m for m in messages if m["is_system"]]
    assert any("timeout was removed" in m["content"] for m in sys_msgs)


# ---------------------------------------------------------------------------
# Ban / Unban
# ---------------------------------------------------------------------------

def test_owner_can_ban_member(alice_client, alice_uid, bob_uid):
    """Owner can permanently ban a member from the group."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/kick",
                             data={"user_id": bob_uid, "permanent": "1"},
                             follow_redirects=True)
    assert b"has been banned" in resp.data
    assert db.is_group_member_banned(group["id"], bob_uid)


def test_banned_user_cannot_rejoin_via_code(alice_uid, bob_uid):
    """A banned user should not be able to rejoin via invite code."""
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.ban_group_member(group["id"], bob_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post("/groups/join",
                      data={"invite_code": group["invite_code"]},
                      follow_redirects=True)
        assert b"banned" in resp.data


def test_unban_member(alice_client, alice_uid, bob_uid):
    """Owner/mod can revoke a ban, allowing the user to rejoin."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.ban_group_member(group["id"], bob_uid)
    assert db.is_group_member_banned(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/unban",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"ban has been revoked" in resp.data
    assert not db.is_group_member_banned(group["id"], bob_uid)


def test_unban_non_banned_member(alice_client, alice_uid, bob_uid):
    """Unbanning a non-banned user should show an error."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/unban",
                             data={"user_id": bob_uid},
                             follow_redirects=True)
    assert b"not banned" in resp.data


def test_banned_user_not_in_members_list(alice_client, alice_uid, bob_uid):
    """Banned users should not appear in the regular members list."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.ban_group_member(group["id"], bob_uid)
    members = db.get_group_members(group["id"])
    member_ids = [m["user_id"] for m in members]
    assert bob_uid not in member_ids


def test_banned_members_in_banned_list(alice_client, alice_uid, bob_uid):
    """Banned users should appear in the banned members list."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.ban_group_member(group["id"], bob_uid)
    banned = db.get_group_banned_members(group["id"])
    banned_ids = [m["user_id"] for m in banned]
    assert bob_uid in banned_ids


def test_cannot_add_banned_user(alice_client, alice_uid, bob_uid):
    """Adding a banned user should fail with an appropriate message."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.ban_group_member(group["id"], bob_uid)
    resp = alice_client.post(f"/groups/{group['id']}/members/add",
                             data={"username": "bob"},
                             follow_redirects=True)
    assert b"banned" in resp.data


def test_kick_without_ban_allows_rejoin(alice_uid, bob_uid):
    """Kicked (non-banned) user can rejoin the group via invite code."""
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.remove_group_member(group["id"], bob_uid)
    assert not db.is_group_member(group["id"], bob_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post("/groups/join",
                      data={"invite_code": group["invite_code"]},
                      follow_redirects=True)
        assert resp.status_code == 200
        assert db.is_group_member(group["id"], bob_uid)


# ---------------------------------------------------------------------------
# Regenerate invite code
# ---------------------------------------------------------------------------

def test_owner_can_regenerate_invite_code(alice_client, alice_uid):
    """Owner should be able to regenerate the invite code."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    old_code = group["invite_code"]
    resp = alice_client.post(f"/groups/{group['id']}/regenerate_code",
                             follow_redirects=True)
    assert b"Invite code regenerated" in resp.data
    updated = db.get_group_chat(group["id"])
    assert updated["invite_code"] != old_code


def test_non_owner_cannot_regenerate_code(alice_uid, bob_uid):
    """Non-owners should not be able to regenerate the invite code."""
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid, role="moderator")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/regenerate_code",
                      follow_redirects=True)
        assert b"Only the group owner" in resp.data


def test_old_code_invalidated_after_regenerate(alice_client, alice_uid, bob_uid):
    """After regeneration, the old invite code should no longer work."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    old_code = group["invite_code"]
    alice_client.post(f"/groups/{group['id']}/regenerate_code")
    found = db.get_group_chat_by_invite(old_code)
    assert found is None


def test_db_regenerate_invite_code(alice_uid):
    """DB helper should generate a new code and invalidate the old one."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    old_code = group["invite_code"]
    new_code = db.regenerate_group_invite_code(group["id"])
    assert new_code != old_code
    assert len(new_code) == 8
    assert db.get_group_chat_by_invite(old_code) is None
    assert db.get_group_chat_by_invite(new_code) is not None


# ---------------------------------------------------------------------------
# Admin take ownership
# ---------------------------------------------------------------------------

def test_admin_can_take_ownership(admin_client, admin_uid, alice_uid):
    """Admin should be able to take ownership of any group."""
    import db
    group = db.create_group_chat("Test", alice_uid)
    resp = admin_client.post(f"/groups/{group['id']}/admin_takeover",
                             follow_redirects=True)
    assert b"now the owner" in resp.data
    assert db.get_group_member_role(group["id"], admin_uid) == "owner"
    assert db.get_group_member_role(group["id"], alice_uid) == "moderator"


def test_admin_can_take_ownership_of_global(admin_client, admin_uid):
    """Admin should be able to take ownership of the global chat."""
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    resp = admin_client.post(f"/groups/{group['id']}/admin_takeover",
                             follow_redirects=True)
    assert b"now the owner" in resp.data
    assert db.get_group_member_role(group["id"], admin_uid) == "owner"


def test_non_admin_cannot_take_ownership(alice_uid, bob_uid):
    """Non-admin users should not be able to take ownership."""
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/admin_takeover",
                      follow_redirects=True)
        assert b"Admin access required" in resp.data


# ---------------------------------------------------------------------------
# Chat disabled feature
# ---------------------------------------------------------------------------

def test_chat_disabled_user_cannot_create_group(alice_uid):
    """A user with chat disabled should not be able to create a group."""
    import db
    from app import app
    db.set_user_chat_disabled(alice_uid, True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "alice", "password": "alice123"})
        resp = c.get("/groups/new", follow_redirects=True)
        assert b"chat privileges have been disabled" in resp.data


def test_chat_disabled_user_cannot_send_group_message(alice_uid, bob_uid):
    """A user with chat disabled should not be able to send group messages."""
    import db
    from app import app
    group = db.create_group_chat("Test", alice_uid)
    db.add_group_member(group["id"], bob_uid)
    db.set_user_chat_disabled(bob_uid, True)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        c.post("/login", data={"username": "bob", "password": "bob123"})
        resp = c.post(f"/groups/{group['id']}/send",
                      data={"content": "test message"},
                      follow_redirects=True)
        assert b"chat privileges have been disabled" in resp.data


def test_admin_can_toggle_chat(admin_client, admin_uid, alice_uid):
    """Admin should be able to disable and re-enable chat for a user."""
    import db
    assert not db.is_user_chat_disabled(alice_uid)
    # Disable
    resp = admin_client.post(f"/admin/users/{alice_uid}/toggle_chat",
                             follow_redirects=True)
    assert db.is_user_chat_disabled(alice_uid)
    # Re-enable
    resp = admin_client.post(f"/admin/users/{alice_uid}/toggle_chat",
                             follow_redirects=True)
    assert not db.is_user_chat_disabled(alice_uid)


def test_db_chat_disabled_helpers(alice_uid):
    """DB helpers for chat disable should work correctly."""
    import db
    assert not db.is_user_chat_disabled(alice_uid)
    db.set_user_chat_disabled(alice_uid, True)
    assert db.is_user_chat_disabled(alice_uid)
    db.set_user_chat_disabled(alice_uid, False)
    assert not db.is_user_chat_disabled(alice_uid)


# ---------------------------------------------------------------------------
# Global chat – site admin kick in global
# ---------------------------------------------------------------------------

def test_site_admin_can_kick_in_global(admin_client, admin_uid, alice_uid):
    """Site admin should be able to kick users from the global chat."""
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    db.add_group_member(group["id"], alice_uid)
    resp = admin_client.post(f"/groups/{group['id']}/kick",
                             data={"user_id": alice_uid},
                             follow_redirects=True)
    assert b"has been removed" in resp.data


def test_site_admin_can_ban_in_global(admin_client, admin_uid, alice_uid):
    """Site admin should be able to ban users from the global chat."""
    import db
    group = db.get_or_create_global_chat()
    db.add_group_member(group["id"], admin_uid)
    db.add_group_member(group["id"], alice_uid)
    resp = admin_client.post(f"/groups/{group['id']}/kick",
                             data={"user_id": alice_uid, "permanent": "1"},
                             follow_redirects=True)
    assert b"has been banned" in resp.data
    assert db.is_group_member_banned(group["id"], alice_uid)
