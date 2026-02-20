"""
BananaWiki – Telegram Sync/Backup Module

Automatically backs up runtime artifacts to Telegram when significant changes
occur (user signups, page edits, settings changes, file uploads, etc.).

Configuration in config.py:
    SYNC           = True/False
    SYNC_TOKEN     = "your-telegram-bot-token"
    SYNC_USERID    = "your-telegram-user-id"
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

# ---------------------------------------------------------------------------
#  Module-level state (thread-safe)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_pending_changes: list[dict] = []
_last_backup_time: float = 0
_debounce_timer: threading.Timer | None = None
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
    (DB mutation, file upload/delete, settings change, etc.).
    Log-only changes do NOT call this function.
    """
    if not is_enabled():
        return

    global _debounce_timer

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
        time_since_last = now - _last_backup_time
        delay = max(DEBOUNCE_DELAY, MIN_BACKUP_INTERVAL - time_since_last)

        _debounce_timer = threading.Timer(delay, _execute_backup)
        _debounce_timer.daemon = True
        _debounce_timer.start()


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------
def _execute_backup() -> None:
    """Create a zip of all runtime artifacts and send it to Telegram."""
    global _last_backup_time, _debounce_timer

    with _lock:
        if not _pending_changes:
            return
        changes = _pending_changes.copy()
        _pending_changes.clear()
        _debounce_timer = None

    logger = _get_logger()
    zip_path = None

    try:
        zip_path, excluded_files = _create_backup(changes)

        if zip_path:
            success = _send_to_telegram(zip_path, changes, excluded_files)
            if success:
                with _lock:
                    _last_backup_time = time.time()
                logger.info(
                    f"SYNC | Backup sent successfully ({len(changes)} change(s))"
                )
            else:
                logger.error("SYNC | Failed to send backup to Telegram")
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
                zf.write(config_path, "config/config.py")
                current_size += cfg_size

            # 3. Secret key (needed for session restoration) -------------
            if os.path.exists(config.SECRET_KEY_FILE):
                sk_size = os.path.getsize(config.SECRET_KEY_FILE)
                zf.write(config.SECRET_KEY_FILE, "instance/.secret_key")
                current_size += sk_size

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

            # 5. Upload assets -------------------------------------------
            upload_dir = config.UPLOAD_FOLDER
            if os.path.isdir(upload_dir):
                for fname in sorted(os.listdir(upload_dir)):
                    fpath = os.path.join(upload_dir, fname)
                    if not os.path.isfile(fpath) or fname == ".gitkeep":
                        continue
                    file_size = os.path.getsize(fpath)
                    if current_size + file_size < max_size:
                        zf.write(fpath, f"uploads/{fname}")
                        current_size += file_size
                    else:
                        excluded_files.append(
                            (f"uploads/{fname}", file_size, "Exceeds size limit")
                        )

            # 6. Backup manifest -----------------------------------------
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
    caption = (
        f"\U0001f34c BananaWiki Backup\n"
        f"\U0001f4c5 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"\U0001f4dd Changes: {change_types}\n"
        f"\U0001f4e6 {len(changes)} change(s)"
    )
    if excluded_files:
        caption += f"\n\u26a0\ufe0f {len(excluded_files)} file(s) excluded (size limit)"

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
