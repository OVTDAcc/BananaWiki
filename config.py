"""
BananaWiki Configuration File
Customize your instance settings here.
"""

import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# =============================================================================
# Networking Configuration
# =============================================================================
# Port Gunicorn binds to. Each app on the server gets its own port.
PORT = 5001

# Gunicorn bind address. The default (127.0.0.1) is correct for the typical
# deployment where nginx acts as the public-facing reverse proxy.
# Change to 0.0.0.0 only if Gunicorn must be reachable directly (no proxy).
HOST = "127.0.0.1"

# =============================================================================
# Reverse Proxy Support
# =============================================================================
# Set to True when running behind nginx (or any other reverse proxy).
# This enables Flask's ProxyFix so the app sees the real client IP and
# the correct scheme (https) from the X-Forwarded-* headers.
PROXY_MODE = True

# =============================================================================
# Security
# =============================================================================
SECRET_KEY_FILE = os.path.join(BASE_DIR, "instance", ".secret_key")


def _load_secret_key():
    """Load or generate a persistent secret key."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    instance_dir = os.path.dirname(SECRET_KEY_FILE)
    os.makedirs(instance_dir, exist_ok=True)

    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
            file_key = f.read().strip()
        if file_key:
            return file_key

    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(new_key)
    os.chmod(SECRET_KEY_FILE, 0o600)
    return new_key


SECRET_KEY = _load_secret_key()

# =============================================================================
# Database
# =============================================================================
DATABASE_PATH = os.path.join(BASE_DIR, "instance", "bananawiki.db")

# =============================================================================
# Uploads
# =============================================================================
UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
# Note: SVG is intentionally disallowed due to potential embedded script/XSS risks.
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# =============================================================================
# Page Attachments
# =============================================================================
# Stored outside the static folder so they are served through an authenticated
# route and not directly accessible by URL.
ATTACHMENT_FOLDER = os.path.join(BASE_DIR, "instance", "attachments")
MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024  # 5 MB per attachment
ATTACHMENT_ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "md", "csv", "json", "xml", "zip", "tar", "gz",
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "webm", "mp3", "ogg",
    "py", "js", "ts", "html", "css", "sh",
}

# =============================================================================
# Chat Attachments
# =============================================================================
# Stored outside the static folder (authenticated download route).
CHAT_ATTACHMENT_FOLDER = os.path.join(BASE_DIR, "instance", "chat_attachments")
CHAT_ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "txt", "md", "csv", "json", "xml", "zip", "tar", "gz",
    "png", "jpg", "jpeg", "gif", "webp",
}

# Note: chat attachment size limits, daily attachment quotas, and cleanup schedule
# are now fully managed via Admin → Settings in the web interface.

# =============================================================================
# Logging
# =============================================================================
# Logging level controls the verbosity of logs
# Available levels:
#   - "off":      No logging at all
#   - "minimal":  Only critical errors and warnings
#   - "medium":   Errors, warnings, and important actions (logins, signups, admin actions)
#   - "verbose":  Medium + all user actions (page edits, profile changes, etc.)
#   - "debug":    All of the above + every HTTP request and detailed debug info
# Default: "verbose" (highest useful level for production)
LOGGING_LEVEL = "verbose"

# Log file path
LOG_FILE = os.path.join(BASE_DIR, "logs", "bananawiki.log")

# =============================================================================
# Page History
# =============================================================================
# Enable or disable the page history viewer. When True (the default), every
# edit, title change, and revert is recorded and can be viewed or reverted.
# Reverting creates a new history entry — nothing is ever deleted from history.
# Set to False to hide all history routes (/history, /revert, etc.) from users.
PAGE_HISTORY_ENABLED = True

# =============================================================================
# Experimental Obsidian Sync
# =============================================================================
# Enable the local Obsidian pull/push integration. The sync script reuses the
# existing BananaWiki user accounts and only allows editor/admin roles.
EXPERIMENTAL_OBSIDIAN_SYNC = False

# =============================================================================
# Invite Codes
# =============================================================================
# How long invite codes last before expiring (in hours)
INVITE_CODE_EXPIRY_HOURS = 48

# =============================================================================
# Page Reservations
# =============================================================================
# How long a page reservation lasts before expiring (in hours)
PAGE_RESERVATION_DURATION_HOURS = 48

# Cooldown period after a reservation ends before user can re-reserve (in hours)
PAGE_RESERVATION_COOLDOWN_HOURS = 24

# =============================================================================
# Telegram Sync / Backup
# =============================================================================
# It is STRONGLY RECOMMENDED to enable sync so that runtime data (database,
# uploads, config, logs) is automatically backed up to Telegram whenever a
# significant change occurs (user signup, page edit, settings change, etc.).
#
# SYNC         – Enable or disable the sync feature (default: off)
# SYNC_TOKEN   – Telegram Bot API token (from @BotFather)
# SYNC_USERID  – Telegram user/chat ID to receive backups
SYNC = False
SYNC_TOKEN = ""
SYNC_USERID = ""

# Smart backup options for Telegram sync
# These control how backups are created and sent based on size
SYNC_SPLIT_THRESHOLD = 45 * 1024 * 1024  # 45 MB - split if backup exceeds this
SYNC_COMPRESS_LEVEL = 9  # ZIP compression level (0-9, higher = better compression)
SYNC_INCLUDE_CHAT_ATTACHMENTS = True  # Include chat attachments in backups
