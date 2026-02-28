"""
Tests for the BananaWiki Telegram Sync/Backup module.
"""

import io
import json
import os
import sys
import tempfile
import time
import zipfile
from unittest.mock import patch, MagicMock

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
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(config, "LOG_FILE", str(tmp_path / "logs" / "test.log"))
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "instance" / ".secret_key"))
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


@pytest.fixture(autouse=True)
def reset_sync_state(monkeypatch):
    """Reset sync module state and disable actual backups for each test."""
    import sync
    monkeypatch.setattr(config, "SYNC", False)
    monkeypatch.setattr(config, "SYNC_TOKEN", "")
    monkeypatch.setattr(config, "SYNC_USERID", "")
    with sync._lock:
        sync._pending_changes.clear()
        sync._last_backup_time = 0
        sync._first_pending_time = 0
        if sync._debounce_timer is not None:
            sync._debounce_timer.cancel()
            sync._debounce_timer = None
    yield


# -----------------------------------------------------------------------
# Config tests
# -----------------------------------------------------------------------
def test_sync_config_defaults():
    """SYNC, SYNC_TOKEN, SYNC_USERID should exist on the config module."""
    assert hasattr(config, "SYNC")
    assert hasattr(config, "SYNC_TOKEN")
    assert hasattr(config, "SYNC_USERID")


# -----------------------------------------------------------------------
# is_enabled tests
# -----------------------------------------------------------------------
def test_sync_disabled_by_default():
    import sync
    assert sync.is_enabled() is False


def test_sync_enabled_when_configured(monkeypatch):
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    assert sync.is_enabled() is True


def test_sync_disabled_without_token(monkeypatch):
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    assert sync.is_enabled() is False


def test_sync_disabled_without_userid(monkeypatch):
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "")
    assert sync.is_enabled() is False


# -----------------------------------------------------------------------
# notify_change tests
# -----------------------------------------------------------------------
def test_notify_change_noop_when_disabled():
    """notify_change should not queue anything when sync is disabled."""
    import sync
    sync.notify_change("test_change", "test description")
    assert len(sync._pending_changes) == 0


def test_notify_change_queues_when_enabled(monkeypatch):
    """notify_change should queue a change and schedule a timer."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    # Mock the Timer to prevent actual backup execution
    with patch("sync.threading.Timer") as mock_timer:
        mock_timer_instance = MagicMock()
        mock_timer.return_value = mock_timer_instance

        sync.notify_change("user_signup", "User 'testuser' registered")

        assert len(sync._pending_changes) == 1
        assert sync._pending_changes[0]["type"] == "user_signup"
        assert sync._pending_changes[0]["description"] == "User 'testuser' registered"
        assert "timestamp" in sync._pending_changes[0]
        mock_timer_instance.start.assert_called_once()


def test_notify_change_debounces_multiple_calls(monkeypatch):
    """Multiple rapid changes should be merged (single timer)."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer_instance = MagicMock()
        mock_timer.return_value = mock_timer_instance

        sync.notify_change("page_create", "Page 'test1' created")
        sync.notify_change("page_edit", "Page 'test1' edited")
        sync.notify_change("file_upload", "Image uploaded")

        assert len(sync._pending_changes) == 3
        # The previous timers should have been cancelled and a new one started
        assert mock_timer_instance.cancel.call_count == 2  # 2nd and 3rd calls cancel previous


# -----------------------------------------------------------------------
# _create_backup tests
# -----------------------------------------------------------------------
def test_create_backup_produces_valid_zip(tmp_path, monkeypatch):
    """Backup should produce a valid zip with expected contents."""
    import sync
    import db

    # Allow sensitive artifacts for this test
    monkeypatch.setattr(config, "SYNC_INCLUDE_SENSITIVE", True)

    # Create some test data
    db.create_user("testuser", "hash123", role="user")

    # Create a log file
    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    monkeypatch.setattr(config, "LOG_FILE", os.path.join(log_dir, "test.log"))
    with open(os.path.join(log_dir, "test.log"), "w") as f:
        f.write("test log entry\n")

    # Create secret key file
    instance_dir = str(tmp_path / "instance")
    os.makedirs(instance_dir, exist_ok=True)
    secret_key_path = os.path.join(instance_dir, ".secret_key")
    monkeypatch.setattr(config, "SECRET_KEY_FILE", secret_key_path)
    with open(secret_key_path, "w") as f:
        f.write("test-secret-key")

    changes = [{"type": "test", "description": "test change", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        assert zip_path is not None
        assert os.path.exists(zip_path)
        assert len(excluded) == 0

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "database/bananawiki.db" in names
            assert "config/config.py" in names
            # Uploads are sent as individual Telegram messages, not in the zip
            assert not any(n.startswith("uploads/") for n in names)
            assert "logs/test.log" in names
            assert "instance/.secret_key" in names
            assert "backup_manifest.json" in names

            # Check manifest content
            manifest = json.loads(zf.read("backup_manifest.json"))
            assert manifest["changes"] == changes
            assert manifest["excluded_files"] == []
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


def test_create_backup_excludes_gitkeep(tmp_path, monkeypatch):
    """Uploads (including .gitkeep) are not included in the backup zip."""
    import sync

    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)
    with open(os.path.join(upload_dir, ".gitkeep"), "w") as f:
        f.write("")
    with open(os.path.join(upload_dir, "test.png"), "wb") as f:
        f.write(b"fake image")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # Uploads are sent individually, not bundled in the zip
            assert not any(n.startswith("uploads/") for n in names)
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


def test_create_backup_excludes_large_log(tmp_path, monkeypatch):
    """Log files exceeding the Telegram limit should be excluded with a reason."""
    import sync

    monkeypatch.setattr(config, "SYNC_INCLUDE_SENSITIVE", True)
    # Set a tiny file limit for testing
    monkeypatch.setattr(sync, "TELEGRAM_FILE_LIMIT", 2048)

    log_dir = str(tmp_path / "logs")
    os.makedirs(log_dir, exist_ok=True)
    monkeypatch.setattr(config, "LOG_FILE", os.path.join(log_dir, "test.log"))
    # Create a log file larger than the limit
    with open(os.path.join(log_dir, "test.log"), "w") as f:
        f.write("x" * 2000)

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        assert len(excluded) > 0
        excluded_names = [e[0] for e in excluded]
        assert "logs/test.log" in excluded_names

        # Manifest should also record the exclusion
        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("backup_manifest.json"))
            assert len(manifest["excluded_files"]) > 0
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


# -----------------------------------------------------------------------
# _send_to_telegram tests
# -----------------------------------------------------------------------
def test_send_to_telegram_success(tmp_path, monkeypatch):
    """Verify that _send_to_telegram builds correct request to Telegram API."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    # Create a small test zip
    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]

    # Mock urlopen to simulate Telegram API success
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"ok": True}).encode()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("sync.urlopen", return_value=mock_response) as mock_urlopen:
        result = sync._send_to_telegram(zip_path, changes, [])
        assert result is True

        # Verify the request was made to the correct URL
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "123:TESTTOKEN" in req.full_url
        assert "sendDocument" in req.full_url
        assert "multipart/form-data" in req.get_header("Content-type")


def test_send_to_telegram_failure(tmp_path, monkeypatch):
    """Verify that _send_to_telegram handles API failures gracefully."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"ok": False, "description": "error"}).encode()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("sync.urlopen", return_value=mock_response):
        result = sync._send_to_telegram(zip_path, changes, [])
        assert result is False


def test_send_to_telegram_oversized_file(tmp_path, monkeypatch):
    """Files larger than Telegram limit should be rejected."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(sync, "TELEGRAM_FILE_LIMIT", 100)

    zip_path = str(tmp_path / "test_backup.zip")
    with open(zip_path, "wb") as f:
        f.write(b"x" * 200)

    result = sync._send_to_telegram(zip_path, [], [])
    assert result is False


def test_send_to_telegram_missing_credentials(tmp_path, monkeypatch):
    """Missing token or user_id should return False."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    result = sync._send_to_telegram(zip_path, [], [])
    assert result is False


# -----------------------------------------------------------------------
# _execute_backup tests
# -----------------------------------------------------------------------
def test_execute_backup_sends_and_cleans_up(tmp_path, monkeypatch):
    """_execute_backup should create zip, send, and clean up."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    sync._pending_changes.append(
        {"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}
    )

    with patch.object(sync, "_send_to_telegram", return_value=True) as mock_send:
        sync._execute_backup()

        mock_send.assert_called_once()
        # Check the zip file was cleaned up (removed after send)
        zip_path = mock_send.call_args[0][0]
        assert not os.path.exists(zip_path)

    assert len(sync._pending_changes) == 0
    assert sync._last_backup_time > 0


def test_execute_backup_noop_when_no_changes():
    """_execute_backup should do nothing when there are no pending changes."""
    import sync

    with patch.object(sync, "_create_backup") as mock_create:
        sync._execute_backup()
        mock_create.assert_not_called()


# -----------------------------------------------------------------------
# Integration: routes trigger sync
# -----------------------------------------------------------------------
def test_signup_triggers_sync(client, admin_user, monkeypatch):
    """User signup should queue a sync change when enabled."""
    import sync
    import db
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    # Generate invite code
    code = db.generate_invite_code(admin_user)

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        resp = client.post("/signup", data={
            "username": "newuser",
            "password": "password123",
            "confirm_password": "password123",
            "invite_code": code,
        })
        assert resp.status_code == 302

    # Check that a change was queued
    found = any(c["type"] == "user_signup" for c in sync._pending_changes)
    assert found


def test_create_page_triggers_sync(logged_in_admin, monkeypatch):
    """Creating a page should queue a sync change when enabled."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        resp = logged_in_admin.post("/create-page", data={
            "title": "Test Page",
            "content": "Hello world",
            "category_id": "",
        })
        assert resp.status_code == 302

    found = any(c["type"] == "page_create" for c in sync._pending_changes)
    assert found


def test_admin_settings_triggers_sync(logged_in_admin, monkeypatch):
    """Updating admin settings should queue a sync change when enabled."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        resp = logged_in_admin.post("/admin/settings", data={
            "site_name": "TestWiki",
            "primary_color": "#aabbcc",
            "secondary_color": "#112233",
            "accent_color": "#445566",
            "text_color": "#778899",
            "sidebar_color": "#001122",
            "bg_color": "#334455",
        })
        assert resp.status_code == 302

    found = any(c["type"] == "settings_update" for c in sync._pending_changes)
    assert found


def test_no_sync_when_disabled(logged_in_admin, monkeypatch):
    """Operations should not queue sync changes when sync is disabled."""
    import sync
    monkeypatch.setattr(config, "SYNC", False)

    logged_in_admin.post("/create-page", data={
        "title": "No Sync Page",
        "content": "Hello",
        "category_id": "",
    })

    assert len(sync._pending_changes) == 0


# -----------------------------------------------------------------------
# Debounce / rate limiting tests
# -----------------------------------------------------------------------
def test_debounce_respects_min_interval(monkeypatch):
    """Timer delay should respect MIN_BACKUP_INTERVAL after a recent backup."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    monkeypatch.setattr(sync, "DEBOUNCE_DELAY", 10)
    monkeypatch.setattr(sync, "MIN_BACKUP_INTERVAL", 300)

    # Simulate a recent backup
    sync._last_backup_time = time.time() - 60  # 60 seconds ago

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        sync.notify_change("test", "test")

        # Delay should be ~240 seconds (300 - 60), not 10
        call_args = mock_timer.call_args
        delay = call_args[0][0]
        assert delay > 200  # Should be close to 240


def test_debounce_uses_debounce_delay_when_no_recent_backup(monkeypatch):
    """Timer delay should use DEBOUNCE_DELAY when no recent backup."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    monkeypatch.setattr(sync, "DEBOUNCE_DELAY", 60)
    monkeypatch.setattr(sync, "MIN_BACKUP_INTERVAL", 300)

    sync._last_backup_time = 0  # No recent backup

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        sync.notify_change("test", "test")

        call_args = mock_timer.call_args
        delay = call_args[0][0]
        # MIN_BACKUP_INTERVAL - time_since_last would be huge (negative after subtraction
        # from time.time()), but max(DEBOUNCE_DELAY, ...) means it should be >= DEBOUNCE_DELAY
        assert delay >= 60


# -----------------------------------------------------------------------
# Telegram caption tests
# -----------------------------------------------------------------------
def test_telegram_caption_includes_excluded_files(tmp_path, monkeypatch):
    """When files are excluded, caption should mention it."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    excluded = [("uploads/huge.png", 99999999, "Exceeds size limit")]

    captured_body = {}

    def mock_urlopen(req, **kwargs):
        captured_body["data"] = req.data
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        result = sync._send_to_telegram(zip_path, changes, excluded)
        assert result is True

    # Verify the body contains the exclusion warning
    body_text = captured_body["data"].decode("utf-8", errors="replace")
    assert "excluded" in body_text.lower()


# -----------------------------------------------------------------------
# Max debounce wait tests
# -----------------------------------------------------------------------
def test_debounce_max_wait_fires_soon_when_first_change_is_old(monkeypatch):
    """Backup delay should be short when first pending change is near MAX_DEBOUNCE_WAIT."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    monkeypatch.setattr(sync, "DEBOUNCE_DELAY", 60)
    monkeypatch.setattr(sync, "MAX_DEBOUNCE_WAIT", 300)

    # Simulate first pending change was 295 seconds ago (5 seconds left in window)
    sync._first_pending_time = time.time() - 295

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        sync.notify_change("test", "test")

        call_args = mock_timer.call_args
        delay = call_args[0][0]
        # Should be capped at ~5 seconds remaining, well below DEBOUNCE_DELAY
        assert delay <= 10


def test_execute_backup_resets_first_pending_time():
    """_execute_backup should reset _first_pending_time after draining changes."""
    import sync

    sync._first_pending_time = time.time() - 100
    sync._pending_changes.append(
        {"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}
    )

    with patch.object(sync, "_send_to_telegram", return_value=True):
        sync._execute_backup()

    assert sync._first_pending_time == 0


# -----------------------------------------------------------------------
# Per-upload notification tests
# -----------------------------------------------------------------------
def test_notify_file_upload_noop_when_disabled(tmp_path):
    """notify_file_upload should do nothing when sync is disabled."""
    import sync
    img_path = str(tmp_path / "test.png")
    with open(img_path, "wb") as f:
        f.write(b"fake")

    with patch.object(sync, "_do_send_upload") as mock_send:
        sync.notify_file_upload("test.png", img_path)
        # Give any spurious thread a moment
        time.sleep(0.05)
        mock_send.assert_not_called()


def test_notify_file_upload_sends_immediately(tmp_path, monkeypatch):
    """notify_file_upload should spawn a thread that calls _do_send_upload."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    img_path = str(tmp_path / "test.png")
    with open(img_path, "wb") as f:
        f.write(b"fake image data")

    calls = []

    def fake_do_send(filename, filepath):
        calls.append((filename, filepath))

    with patch.object(sync, "_do_send_upload", side_effect=fake_do_send):
        sync.notify_file_upload("test.png", img_path)
        # Allow background thread to run
        time.sleep(0.2)

    assert len(calls) == 1
    assert calls[0] == ("test.png", img_path)


def test_do_send_upload_stores_message_id(tmp_path, monkeypatch):
    """_do_send_upload should store the returned message_id."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    img_path = str(tmp_path / "photo.png")
    with open(img_path, "wb") as f:
        f.write(b"fake image data")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": 777}}
    ).encode()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("sync.urlopen", return_value=mock_response):
        sync._do_send_upload("photo.png", img_path)

    assert sync._get_upload_msg_id("photo.png") == 777


def test_do_send_upload_skips_missing_file(tmp_path, monkeypatch):
    """_do_send_upload should log a warning and return if file is missing."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    with patch("sync.urlopen") as mock_urlopen:
        sync._do_send_upload("ghost.png", str(tmp_path / "ghost.png"))
        mock_urlopen.assert_not_called()


def test_do_send_upload_skips_oversized_file(tmp_path, monkeypatch):
    """_do_send_upload should skip files exceeding TELEGRAM_FILE_LIMIT."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(sync, "TELEGRAM_FILE_LIMIT", 100)

    img_path = str(tmp_path / "huge.png")
    with open(img_path, "wb") as f:
        f.write(b"x" * 200)

    with patch("sync.urlopen") as mock_urlopen:
        sync._do_send_upload("huge.png", img_path)
        mock_urlopen.assert_not_called()


def test_notify_file_deleted_noop_when_disabled(tmp_path):
    """notify_file_deleted should do nothing when sync is disabled."""
    import sync

    with patch.object(sync, "_do_send_deletion_notice") as mock_send:
        sync.notify_file_deleted("test.png")
        time.sleep(0.05)
        mock_send.assert_not_called()


def test_notify_file_deleted_spawns_thread(monkeypatch):
    """notify_file_deleted should spawn a thread that calls _do_send_deletion_notice."""
    import sync
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    calls = []

    def fake_do_notice(filename):
        calls.append(filename)

    with patch.object(sync, "_do_send_deletion_notice", side_effect=fake_do_notice):
        sync.notify_file_deleted("removed.png")
        time.sleep(0.2)

    assert calls == ["removed.png"]


def test_do_send_deletion_notice_replies_to_original(tmp_path, monkeypatch):
    """_do_send_deletion_notice should include reply_to_message_id when known."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    # Pre-store a message ID for the file
    sync._store_upload_msg_id("photo.png", 123)

    captured = {}

    def mock_urlopen(req, **kwargs):
        captured["body"] = json.loads(req.data.decode())
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 456}}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        sync._do_send_deletion_notice("photo.png")

    assert captured["body"].get("reply_to_message_id") == 123
    assert "photo.png" in captured["body"]["text"]


def test_do_send_deletion_notice_no_reply_when_unknown(tmp_path, monkeypatch):
    """_do_send_deletion_notice should send without reply_to if message_id is unknown."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    captured = {}

    def mock_urlopen(req, **kwargs):
        captured["body"] = json.loads(req.data.decode())
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 789}}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        sync._do_send_deletion_notice("unknown.png")

    assert "reply_to_message_id" not in captured["body"]
    assert "unknown.png" in captured["body"]["text"]


def test_upload_msg_id_store_and_retrieve(tmp_path, monkeypatch):
    """Message IDs should be persisted to disk and retrievable."""
    import sync
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    sync._store_upload_msg_id("alpha.png", 100)
    sync._store_upload_msg_id("beta.jpg", 200)

    assert sync._get_upload_msg_id("alpha.png") == 100
    assert sync._get_upload_msg_id("beta.jpg") == 200
    assert sync._get_upload_msg_id("missing.gif") is None


# -----------------------------------------------------------------------
# Attachment backup tests
# -----------------------------------------------------------------------
def test_create_backup_includes_attachments(tmp_path, monkeypatch):
    """Backup should include files from the attachments folder."""
    import sync

    attach_dir = str(tmp_path / "attachments")
    os.makedirs(attach_dir, exist_ok=True)
    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", attach_dir)

    # Create a fake attachment file
    att_path = os.path.join(attach_dir, "abc123.pdf")
    with open(att_path, "wb") as f:
        f.write(b"fake pdf content")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "attachments/abc123.pdf" in names
        assert not any(e[0].startswith("attachments/") for e in excluded)
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


def test_create_backup_excludes_oversized_attachment(tmp_path, monkeypatch):
    """Attachment files that exceed the size limit should be excluded."""
    import sync
    monkeypatch.setattr(sync, "TELEGRAM_FILE_LIMIT", 2048)

    attach_dir = str(tmp_path / "attachments")
    os.makedirs(attach_dir, exist_ok=True)
    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", attach_dir)

    att_path = os.path.join(attach_dir, "huge.pdf")
    with open(att_path, "wb") as f:
        f.write(b"x" * 2000)

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        excluded_names = [e[0] for e in excluded]
        assert "attachments/huge.pdf" in excluded_names

        with zipfile.ZipFile(zip_path, "r") as zf:
            manifest = json.loads(zf.read("backup_manifest.json"))
            assert any(e["file"] == "attachments/huge.pdf" for e in manifest["excluded_files"])
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


def test_create_backup_no_attachment_folder(tmp_path, monkeypatch):
    """Backup should succeed gracefully when ATTACHMENT_FOLDER does not exist."""
    import sync

    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", str(tmp_path / "nonexistent_attachments"))

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    zip_path, excluded = sync._create_backup(changes)

    try:
        assert zip_path is not None
        assert os.path.exists(zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert not any(n.startswith("attachments/") for n in names)
    finally:
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)


# -----------------------------------------------------------------------
# Integration: attachment routes trigger sync
# -----------------------------------------------------------------------
def test_upload_attachment_triggers_sync(logged_in_admin, monkeypatch, tmp_path):
    """Uploading a page attachment should queue a sync change when enabled."""
    import sync
    import db
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")
    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", str(tmp_path / "attachments"))

    # Create a page to attach to
    page_id = db.create_page("Attach Test", "attach-test", "content")

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        resp = logged_in_admin.post(
            f"/api/page/{page_id}/attachments",
            data={"file": (io.BytesIO(b"hello world"), "test.txt")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200

    found = any(c["type"] == "attachment_upload" for c in sync._pending_changes)
    assert found


def test_delete_attachment_triggers_sync(logged_in_admin, admin_user, monkeypatch, tmp_path):
    """Deleting a page attachment should queue a sync change when enabled."""
    import sync
    import db
    monkeypatch.setattr(config, "SYNC", True)
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:ABC")
    monkeypatch.setattr(config, "SYNC_USERID", "999")

    attach_dir = str(tmp_path / "attachments")
    os.makedirs(attach_dir, exist_ok=True)
    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", attach_dir)

    # Create a page and a real attachment file so the route can find it
    page_id = db.create_page("Delete Attach Test", "delete-attach-test", "content")
    stored_name = "deadbeef.txt"
    att_path = os.path.join(attach_dir, stored_name)
    with open(att_path, "wb") as f:
        f.write(b"data")
    attachment_id = db.add_page_attachment(page_id, stored_name, "original.txt", 4, admin_user)

    with patch("sync.threading.Timer") as mock_timer:
        mock_timer.return_value = MagicMock()
        resp = logged_in_admin.delete(f"/api/attachments/{attachment_id}")
        assert resp.status_code == 200

    found = any(c["type"] == "attachment_delete" for c in sync._pending_changes)
    assert found


# -----------------------------------------------------------------------
# Caption exclusion message tests
# -----------------------------------------------------------------------
def test_telegram_caption_excluded_by_config_not_size_limit(tmp_path, monkeypatch):
    """Caption should say 'excluded from backup', not '(size limit)',
    when files are excluded because SYNC_INCLUDE_SENSITIVE is False."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    # Reason is "Excluded by config" not "Exceeds size limit"
    excluded = [("database/bananawiki.db", 1024, "Excluded by config")]

    captured_body = {}

    def mock_urlopen(req, **kwargs):
        captured_body["data"] = req.data
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        result = sync._send_to_telegram(zip_path, changes, excluded)
        assert result is True

    body_text = captured_body["data"].decode("utf-8", errors="replace")
    assert "excluded from backup" in body_text
    # Must NOT incorrectly say "(size limit)" when excluded by config
    assert "size limit" not in body_text


def test_telegram_caption_excluded_by_size_limit(tmp_path, monkeypatch):
    """Caption should say 'excluded from backup' for size-limited files too."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")

    zip_path = str(tmp_path / "test_backup.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("test.txt", "hello")

    changes = [{"type": "test", "description": "test", "timestamp": "2024-01-01T00:00:00"}]
    excluded = [("attachments/huge.pdf", 60 * 1024 * 1024, "Exceeds size limit")]

    captured_body = {}

    def mock_urlopen(req, **kwargs):
        captured_body["data"] = req.data
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        result = sync._send_to_telegram(zip_path, changes, excluded)
        assert result is True

    body_text = captured_body["data"].decode("utf-8", errors="replace")
    assert "excluded from backup" in body_text


# -----------------------------------------------------------------------
# Deletion notice message ID cleanup tests
# -----------------------------------------------------------------------
def test_deletion_notice_cleans_up_msg_id(tmp_path, monkeypatch):
    """After a successful deletion notice, the stored message_id should be removed."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    # Pre-store a message ID for the file
    sync._store_upload_msg_id("photo.png", 123)
    assert sync._get_upload_msg_id("photo.png") == 123

    def mock_urlopen(req, **kwargs):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "result": {"message_id": 456}}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        sync._do_send_deletion_notice("photo.png")

    # Message ID should be cleaned up after successful deletion notice
    assert sync._get_upload_msg_id("photo.png") is None


def test_deletion_notice_failed_send_keeps_msg_id(tmp_path, monkeypatch):
    """If the deletion notice send fails, the stored message_id should be retained."""
    import sync
    monkeypatch.setattr(config, "SYNC_TOKEN", "123:TESTTOKEN")
    monkeypatch.setattr(config, "SYNC_USERID", "42")
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    sync._store_upload_msg_id("photo.png", 999)

    def mock_urlopen(req, **kwargs):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": False, "description": "error"}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    with patch("sync.urlopen", side_effect=mock_urlopen):
        sync._do_send_deletion_notice("photo.png")

    # Message ID should still be present since the send failed
    assert sync._get_upload_msg_id("photo.png") == 999


def test_delete_upload_msg_id_removes_only_target(tmp_path, monkeypatch):
    """_delete_upload_msg_id should only remove the specified filename."""
    import sync
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    sync._store_upload_msg_id("alpha.png", 100)
    sync._store_upload_msg_id("beta.jpg", 200)

    sync._delete_upload_msg_id("alpha.png")

    assert sync._get_upload_msg_id("alpha.png") is None
    assert sync._get_upload_msg_id("beta.jpg") == 200


def test_delete_upload_msg_id_noop_when_no_store(tmp_path, monkeypatch):
    """_delete_upload_msg_id should not raise when store file doesn't exist."""
    import sync
    monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

    # Should not raise even if the file doesn't exist
    sync._delete_upload_msg_id("ghost.png")
