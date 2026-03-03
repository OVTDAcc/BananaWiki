"""
BananaWiki – Telegram Sync/Backup Module

Automatically backs up runtime artifacts to Telegram when significant changes
occur (user signups, page edits, settings changes, file uploads, etc.).

Configuration in config.py:
    SYNC           = True/False
    SYNC_TOKEN     = "your-telegram-bot-token"
    SYNC_USERID    = "your-telegram-user-id"

Every backup includes the database, config file, secret key, and logs.
The only reason a file is excluded is if it would push the zip over
Telegram's 50 MB limit.
"""

import io
import json
import os
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

import config

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
# Telegram Bot API file size limit (50 MB)
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024

# Minimum seconds between backup sends
MIN_BACKUP_INTERVAL = 300  # 5 minutes

# Debounce delay – wait this many seconds after the last change before sending
DEBOUNCE_DELAY = 60  # 1 minute

# Maximum seconds to wait before forcing a backup, even with continuous changes
MAX_DEBOUNCE_WAIT = 600  # 10 minutes

# Number of retry attempts for failed Telegram sends
MAX_RETRIES = 3

# Base delay between retries in seconds (exponential backoff)
RETRY_BASE_DELAY = 5

# ---------------------------------------------------------------------------
#  Module-level state (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_pending_changes: list[dict] = []
_last_backup_time: float = 0
_first_pending_time: float = 0
_debounce_timer: threading.Timer | None = None
_upload_msgs_lock = threading.Lock()
_logger = None


def _get_logger():
    """Lazily import the wiki logger to avoid circular imports."""
    global _logger
    if _logger is None:
        from wiki_logger import get_logger
        _logger = get_logger()
    return _logger


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    """Return True if Telegram sync is properly configured and enabled."""
    return bool(
        getattr(config, "SYNC", False)
        and getattr(config, "SYNC_TOKEN", "")
        and getattr(config, "SYNC_USERID", "")
    )


def notify_change(change_type: str, description: str = "") -> None:
    """Record a significant change and schedule a debounced backup.

    This is called from Flask routes whenever a runtime artifact changes
    (DB mutation, settings change, etc.).
    Log-only changes do NOT call this function.

    Multiple rapid changes are merged into a single backup.  A backup is
    guaranteed to fire within MAX_DEBOUNCE_WAIT seconds of the first
    queued change, even if new changes keep arriving.
    """
    if not is_enabled():
        return

    global _debounce_timer, _first_pending_time

    with _lock:
        _pending_changes.append(
            {
                "type": change_type,
                "description": description,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Cancel any existing timer and re-schedule
        if _debounce_timer is not None:
            _debounce_timer.cancel()

        now = time.time()
        # Record the time of the very first queued change in this batch
        if _first_pending_time == 0:
            _first_pending_time = now

        time_since_last = now - _last_backup_time
        delay = max(DEBOUNCE_DELAY, MIN_BACKUP_INTERVAL - time_since_last)

        # Cap the delay so the backup fires within MAX_DEBOUNCE_WAIT of the
        # first pending change, preventing indefinite postponement.
        elapsed_since_first = now - _first_pending_time
        delay = min(delay, max(0, MAX_DEBOUNCE_WAIT - elapsed_since_first))

        _debounce_timer = threading.Timer(delay, _execute_backup)
        _debounce_timer.daemon = True
        _debounce_timer.start()


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------
def _execute_backup() -> None:
    """Create a zip of all runtime artifacts and send it to Telegram."""
    global _last_backup_time, _debounce_timer, _first_pending_time

    with _lock:
        if not _pending_changes:
            return
        changes = _pending_changes.copy()
        _pending_changes.clear()
        _debounce_timer = None
        _first_pending_time = 0

    logger = _get_logger()
    zip_path = None

    try:
        zip_path, excluded_files = _create_backup(changes)

        if zip_path:
            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                success = _send_to_telegram(zip_path, changes, excluded_files)
                if success:
                    break
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"SYNC | Attempt {attempt}/{MAX_RETRIES} failed, "
                        f"retrying in {delay}s"
                    )
                    time.sleep(delay)

            if success:
                with _lock:
                    _last_backup_time = time.time()
                logger.info(
                    f"SYNC | Backup sent successfully ({len(changes)} change(s))"
                )
            else:
                logger.error(
                    f"SYNC | Failed to send backup after {MAX_RETRIES} attempts"
                )
    except Exception as exc:
        logger.error(f"SYNC | Backup failed: {exc}")
    finally:
        if zip_path:
            try:
                os.remove(zip_path)
            except OSError:
                pass


def _create_backup(changes: list[dict]) -> tuple[str | None, list[tuple]]:
    """Zip all runtime artifacts and return (zip_path, excluded_files)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"bananawiki_backup_{timestamp}.zip"

    instance_dir = os.path.join(config.BASE_DIR, "instance")
    os.makedirs(instance_dir, exist_ok=True)
    zip_path = os.path.join(instance_dir, zip_filename)

    excluded_files: list[tuple[str, int, str]] = []
    current_size = 0
    # Leave 1 MB margin below Telegram's limit
    max_size = TELEGRAM_FILE_LIMIT - (1024 * 1024)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Database -------------------------------------------------
            if os.path.exists(config.DATABASE_PATH):
                db_size = os.path.getsize(config.DATABASE_PATH)
                if current_size + db_size < max_size:
                    zf.write(config.DATABASE_PATH, "database/bananawiki.db")
                    current_size += db_size
                else:
                    excluded_files.append(
                        ("database/bananawiki.db", db_size, "Exceeds size limit")
                    )

            # 2. Config file ---------------------------------------------
            config_path = os.path.join(config.BASE_DIR, "config.py")
            if os.path.exists(config_path):
                cfg_size = os.path.getsize(config_path)
                if current_size + cfg_size < max_size:
                    zf.write(config_path, "config/config.py")
                    current_size += cfg_size
                else:
                    excluded_files.append(
                        ("config/config.py", cfg_size, "Exceeds size limit")
                    )

            # 3. Secret key (needed for session restoration) -------------
            if os.path.exists(config.SECRET_KEY_FILE):
                sk_size = os.path.getsize(config.SECRET_KEY_FILE)
                if current_size + sk_size < max_size:
                    zf.write(config.SECRET_KEY_FILE, "instance/.secret_key")
                    current_size += sk_size
                else:
                    excluded_files.append(
                        ("instance/.secret_key", sk_size, "Exceeds size limit")
                    )

            # 4. Log files -----------------------------------------------
            log_dir = os.path.dirname(config.LOG_FILE)
            if os.path.isdir(log_dir):
                for log_file in sorted(os.listdir(log_dir)):
                    log_path = os.path.join(log_dir, log_file)
                    if not os.path.isfile(log_path):
                        continue
                    file_size = os.path.getsize(log_path)
                    if current_size + file_size < max_size:
                        zf.write(log_path, f"logs/{log_file}")
                        current_size += file_size
                    else:
                        excluded_files.append(
                            (f"logs/{log_file}", file_size, "Exceeds size limit")
                        )

            # 5. Backup manifest -----------------------------------------
            manifest = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "changes": changes,
                "excluded_files": [
                    {"file": f, "size_bytes": s, "reason": r}
                    for f, s, r in excluded_files
                ],
            }
            zf.writestr("backup_manifest.json", json.dumps(manifest, indent=2))

    except Exception:
        # If zip creation fails, clean up and re-raise
        if os.path.exists(zip_path):
            os.remove(zip_path)
        raise

    return zip_path, excluded_files


def _send_to_telegram(
    zip_path: str,
    changes: list[dict],
    excluded_files: list[tuple],
) -> bool:
    """Upload the backup zip to Telegram via the Bot API sendDocument."""
    token = config.SYNC_TOKEN
    user_id = config.SYNC_USERID
    if not token or not user_id:
        return False

    file_size = os.path.getsize(zip_path)
    if file_size > TELEGRAM_FILE_LIMIT:
        _get_logger().error(
            f"SYNC | Backup file too large ({file_size} bytes), skipping send"
        )
        return False

    # Build a human-readable caption
    change_types = ", ".join(sorted({c["type"] for c in changes}))
    descriptions = [c["description"] for c in changes if c.get("description")]
    caption = (
        f"\U0001f34c BananaWiki Backup\n"
        f"\U0001f4c5 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"\U0001f4dd Changes: {change_types}\n"
        f"\U0001f4e6 {len(changes)} change(s)"
    )
    if descriptions:
        detail_lines = "\n".join(f"  • {d}" for d in descriptions[:10])
        caption += f"\n\U0001f4cb Details:\n{detail_lines}"
        if len(descriptions) > 10:
            caption += f"\n  … and {len(descriptions) - 10} more"
    if excluded_files:
        caption += f"\n\u26a0\ufe0f {len(excluded_files)} file(s) excluded from backup"

    # --- Build multipart/form-data body using stdlib only ----------------
    boundary = f"----BananaWikiSync{int(time.time())}"

    parts: list[bytes] = []

    # chat_id
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    parts.append(f"{user_id}\r\n".encode())

    # caption
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
    parts.append(f"{caption}\r\n".encode())

    # document (file upload)
    filename = os.path.basename(zip_path)
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="document"; '
        f'filename="{filename}"\r\n'.encode()
    )
    parts.append(b"Content-Type: application/zip\r\n\r\n")
    with open(zip_path, "rb") as fp:
        parts.append(fp.read())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    body = b"".join(parts)

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result.get("ok", False)
    except (URLError, OSError, ValueError) as exc:
        _get_logger().error(f"SYNC | Telegram API error: {exc}")
        return False


# ---------------------------------------------------------------------------
#  Per-upload Telegram notifications
# ---------------------------------------------------------------------------
def notify_file_upload(filename: str, filepath: str, display_name: str = "") -> None:
    """Send a newly uploaded file to Telegram as a dedicated message.

    Each upload is sent as an individual document message so that file-size
    limits are applied per file rather than across an entire backup zip.
    The returned Telegram message_id is persisted so that a subsequent
    deletion can reply to the original message.

    *display_name* is shown in the Telegram caption; defaults to *filename*.
    """
    if not is_enabled():
        return
    t = threading.Thread(
        target=_do_send_upload,
        args=(filename, filepath, display_name),
        daemon=True,
    )
    t.start()


def notify_file_deleted(filename: str) -> None:
    """Notify Telegram that an upload was deleted.

    Replies to the original upload message (if the message_id was recorded)
    so the file remains in the chat for reference while the deletion is noted.
    """
    if not is_enabled():
        return
    t = threading.Thread(
        target=_do_send_deletion_notice,
        args=(filename,),
        daemon=True,
    )
    t.start()


def backup_chats_before_cleanup() -> None:
    """Send all chat messages to Telegram before the nightly cleanup.

    Each message is formatted with sender, receiver, IP, timestamp and
    any attachment filenames.  Attachments themselves are sent as documents.
    Runs synchronously (called from the cleanup thread).
    """
    if not is_enabled():
        return

    import db as _db  # local import to avoid circular dependency

    messages = _db.get_all_messages_for_backup()
    if not messages:
        return

    token = config.SYNC_TOKEN
    user_id = config.SYNC_USERID
    if not token or not user_id:
        return

    logger = _get_logger()
    chat_attach_dir = getattr(config, "CHAT_ATTACHMENT_FOLDER", "")

    # Build a single text report
    lines = ["\U0001f4ac Chat backup before cleanup", ""]
    for msg in messages:
        att_names = ", ".join(a["original_name"] for a in msg.get("attachments", []))
        line = (
            f"\u2022 [{msg['created_at']}] {msg['sender_name']} \u2192 {msg['receiver_name']} "
            f"(IP: {msg['ip_address']})\n  {msg['content']}"
        )
        if att_names:
            line += f"\n  \U0001f4ce Attachments: {att_names}"
        lines.append(line)

    text = "\n".join(lines)

    # Telegram messages have a 4096-char limit; split if needed
    chunks = [text[i:i + 4000] for i in range(0, len(text), 4000)]

    for chunk in chunks:
        payload = {"chat_id": user_id, "text": chunk}
        body = json.dumps(payload).encode()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        req = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:
                resp.read()
        except (URLError, OSError, ValueError) as exc:
            logger.error(f"SYNC | Chat backup text send failed: {exc}")

    # Send attachment files
    for msg in messages:
        for att in msg.get("attachments", []):
            filepath = os.path.join(chat_attach_dir, att["filename"]) if chat_attach_dir else ""
            if filepath and os.path.isfile(filepath):
                _do_send_upload(att["filename"], filepath, display_name=att["original_name"])

    logger.info(f"SYNC | Chat backup sent ({len(messages)} message(s))")


# ---------------------------------------------------------------------------
#  Upload message-ID persistence
# ---------------------------------------------------------------------------
def _get_upload_msg_store_path() -> str:
    """Path to the JSON file that maps filenames to Telegram message IDs."""
    return os.path.join(config.BASE_DIR, "instance", "sync_upload_msgs.json")


def _store_upload_msg_id(filename: str, msg_id: int) -> None:
    """Persist a filename → Telegram message_id mapping to disk."""
    with _upload_msgs_lock:
        path = _get_upload_msg_store_path()
        msgs: dict = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    msgs = json.load(f)
            except (OSError, ValueError):
                msgs = {}
        msgs[filename] = msg_id
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(msgs, f, indent=2)


def _get_upload_msg_id(filename: str) -> int | None:
    """Return the stored Telegram message_id for *filename*, or None."""
    with _upload_msgs_lock:
        path = _get_upload_msg_store_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                msgs = json.load(f)
            return msgs.get(filename)
        except (OSError, ValueError):
            return None


def _delete_upload_msg_id(filename: str) -> None:
    """Remove the stored Telegram message_id for *filename* (if present)."""
    with _upload_msgs_lock:
        path = _get_upload_msg_store_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                msgs = json.load(f)
            if filename in msgs:
                del msgs[filename]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(msgs, f, indent=2)
        except (OSError, ValueError):
            pass


# ---------------------------------------------------------------------------
#  Internal helpers for per-upload sends
# ---------------------------------------------------------------------------
def _do_send_upload(filename: str, filepath: str, display_name: str = "") -> None:
    """Send *filepath* to Telegram as a dedicated document message."""
    token = config.SYNC_TOKEN
    user_id = config.SYNC_USERID
    if not token or not user_id:
        return

    if not os.path.isfile(filepath):
        _get_logger().warning(f"SYNC | Upload file not found: {filepath}")
        return

    file_size = os.path.getsize(filepath)
    if file_size > TELEGRAM_FILE_LIMIT:
        _get_logger().warning(
            f"SYNC | Upload '{filename}' too large ({file_size} bytes), skipping"
        )
        return

    label = display_name or filename
    caption = (
        f"\U0001f4ce New upload: {label}\n"
        f"\U0001f4c5 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    boundary = f"----BananaWikiSync{int(time.time())}"
    parts: list[bytes] = []

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="chat_id"\r\n\r\n')
    parts.append(f"{user_id}\r\n".encode())

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(b'Content-Disposition: form-data; name="caption"\r\n\r\n')
    parts.append(f"{caption}\r\n".encode())

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    _MIME = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    content_type = _MIME.get(ext, "application/octet-stream")

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="document"; '
        f'filename="{filename}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    with open(filepath, "rb") as fp:
        parts.append(fp.read())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    body = b"".join(parts)
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                msg_id = result["result"]["message_id"]
                _store_upload_msg_id(filename, msg_id)
                _get_logger().info(
                    f"SYNC | Upload '{filename}' sent (msg_id={msg_id})"
                )
            else:
                _get_logger().error(
                    f"SYNC | Failed to send upload '{filename}': "
                    f"{result.get('description')}"
                )
    except (URLError, OSError, ValueError) as exc:
        _get_logger().error(f"SYNC | Error sending upload '{filename}': {exc}")


def _do_send_deletion_notice(filename: str) -> None:
    """Send a Telegram message noting that *filename* was deleted.

    If the original upload message_id is known, this is sent as a reply so
    the file remains visible in the chat for reference.
    """
    token = config.SYNC_TOKEN
    user_id = config.SYNC_USERID
    if not token or not user_id:
        return

    msg_id = _get_upload_msg_id(filename)

    text = (
        f"\U0001f5d1\ufe0f File deleted: {filename}\n"
        f"\U0001f4c5 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    payload: dict = {"chat_id": user_id, "text": text}
    if msg_id is not None:
        payload["reply_to_message_id"] = msg_id

    body = json.dumps(payload).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                _delete_upload_msg_id(filename)
                _get_logger().info(
                    f"SYNC | Deletion notice sent for '{filename}'"
                )
            else:
                _get_logger().error(
                    f"SYNC | Failed to send deletion notice for '{filename}': "
                    f"{result.get('description')}"
                )
    except (URLError, OSError, ValueError) as exc:
        _get_logger().error(
            f"SYNC | Error sending deletion notice for '{filename}': {exc}"
        )
